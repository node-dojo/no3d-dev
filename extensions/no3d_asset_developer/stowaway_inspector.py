"""Current-file asset payload inspection and narrowly scoped cleanup tools.

The inspector answers one question: what will Blender carry with the datablock
the artist is editing?  It never opens or scans remote library files.  Its
default surface is read-only; mutation is limited to explicit resource packing
and a guarded Scene Clean for an isolated object-asset file.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from typing import Any

import bpy
from bpy.props import StringProperty
from bpy.types import Operator, Panel


_CACHE: dict[str, Any] = {"key": None, "scan": None}


@dataclass
class Target:
    datablock: Any
    source: str


def resolve_target(context) -> Target | None:
    """Resolve only a datablock in the currently open .blend.

    Each editor owns its selection.  There is deliberately no cross-editor
    fallback from the Asset Browser to a viewport object.
    """
    space = getattr(context, "space_data", None)
    space_type = getattr(space, "type", "")

    if space_type == "FILE_BROWSER" and getattr(space, "browse_mode", None) == "ASSETS":
        representation = getattr(context, "asset", None)
        local_id = getattr(representation, "local_id", None) if representation else None
        if local_id is not None:
            return Target(local_id, "Current File Asset")
        return None

    if space_type == "NODE_EDITOR":
        tree = getattr(space, "edit_tree", None)
        if tree is not None and getattr(tree, "library", None) is None:
            return Target(tree, "Active Node Group")
        return None

    if space_type == "VIEW_3D":
        obj = getattr(context, "active_object", None)
        if obj is not None and getattr(obj, "library", None) is None:
            return Target(obj, "Active Object")
        return None

    return None


def _label(datablock) -> str:
    return f"{datablock.bl_rna.identifier}:{datablock.name}"


def _dependency_graph(root):
    """Return the transitive ID dependency closure and shortest paths."""
    dependencies = defaultdict(set)
    for referenced, users in bpy.data.user_map().items():
        for user in users:
            dependencies[user].add(referenced)

    previous = {root: None}
    queue = deque([root])
    while queue:
        user = queue.popleft()
        for referenced in dependencies.get(user, ()):
            if referenced not in previous:
                previous[referenced] = user
                queue.append(referenced)
    return set(previous), previous


def _short_path(target, previous) -> str:
    chain = []
    current = target
    while current is not None:
        chain.append(current.name)
        current = previous.get(current)
    chain.reverse()
    if len(chain) <= 3:
        return " -> ".join(chain)
    return f"{chain[0]} -> ... -> {chain[-1]}"


def _output_path_nodes(node_tree) -> set:
    outputs = [
        node for node in node_tree.nodes
        if node.bl_idname == "NodeGroupOutput"
        and getattr(node, "is_active_output", True)
    ]
    active = set(outputs)
    stack = list(outputs)
    while stack:
        node = stack.pop()
        for socket in node.inputs:
            for link in socket.links:
                source = link.from_node
                if source not in active:
                    active.add(source)
                    stack.append(source)
    return active


def _reference_locations(closure: set) -> dict:
    """Map referenced IDs to the nodes that retain them."""
    locations = defaultdict(list)
    for tree in (item for item in closure if isinstance(item, bpy.types.NodeTree)):
        if not hasattr(tree, "nodes"):
            continue
        active = _output_path_nodes(tree)
        for node in tree.nodes:
            candidates = []
            referenced_tree = getattr(node, "node_tree", None)
            if referenced_tree is not None:
                candidates.append(referenced_tree)
            for socket in node.inputs:
                try:
                    value = socket.default_value
                except (AttributeError, TypeError):
                    continue
                if isinstance(value, bpy.types.ID):
                    candidates.append(value)
            for target in candidates:
                locations[target].append({
                    "node_group": tree.name,
                    "node": node.name,
                    "status": "Live branch" if node in active else "Inactive branch",
                })
    return locations


def _is_packed(datablock) -> bool:
    packed_files = getattr(datablock, "packed_files", None)
    if packed_files is not None:
        return len(packed_files) > 0
    return getattr(datablock, "packed_file", None) is not None


def _all_audited_ids() -> set:
    collections = (
        bpy.data.objects,
        bpy.data.collections,
        bpy.data.meshes,
        bpy.data.materials,
        bpy.data.node_groups,
        bpy.data.images,
        bpy.data.fonts,
        bpy.data.worlds,
        bpy.data.scenes,
        bpy.data.cameras,
        bpy.data.lights,
    )
    return {item for collection in collections for item in collection}


def scan_target(target: Target) -> dict:
    root = target.datablock
    closure, previous = _dependency_graph(root)
    locations = _reference_locations(closure)
    all_ids = _all_audited_ids()

    asset_roots = sorted(
        (_label(item) for item in closure if getattr(item, "asset_data", None) is not None),
        key=str.casefold,
    )
    objects = []
    for item in sorted(
        (item for item in closure if isinstance(item, bpy.types.Object) and item != root),
        key=lambda value: value.name.casefold(),
    ):
        refs = locations.get(item, [])
        statuses = {ref["status"] for ref in refs}
        status = "Live branch" if "Live branch" in statuses else (
            "Inactive branch" if "Inactive branch" in statuses else "Dependency"
        )
        location = refs[0] if refs else {}
        objects.append({
            "name": item.name,
            "type": item.type,
            "status": status,
            "path": _short_path(item, previous),
            "node_group": location.get("node_group", ""),
            "node": location.get("node", ""),
            "hidden": bool(item.hide_viewport or item.hide_render),
        })

    resources = []
    for item in sorted(
        (item for item in closure if isinstance(item, (bpy.types.Image, bpy.types.VectorFont))),
        key=lambda value: value.name.casefold(),
    ):
        resources.append({
            "name": item.name,
            "id_type": item.bl_rna.identifier,
            "packed": _is_packed(item),
            "path": getattr(item, "filepath", ""),
        })

    bakes = []
    for obj in (item for item in closure if isinstance(item, bpy.types.Object)):
        for modifier in obj.modifiers:
            if modifier.type != "NODES":
                continue
            for bake in modifier.bakes:
                node = bake.node
                configured = bake.bake_target
                effective = modifier.bake_target if configured == "INHERIT" else configured
                bakes.append({
                    "object": obj.name,
                    "modifier": modifier.name,
                    "node": node.name if node else f"Bake {bake.bake_id}",
                    "target": effective.title(),
                    "directory": bake.directory or modifier.bake_directory,
                })

    debris = all_ids - closure
    return {
        "root_name": root.name,
        "root_type": root.bl_rna.identifier,
        "source": target.source,
        "closure": closure,
        "previous": previous,
        "counts": Counter(item.bl_rna.identifier for item in closure),
        "debris_counts": Counter(item.bl_rna.identifier for item in debris),
        "asset_roots": asset_roots,
        "objects": objects,
        "resources": resources,
        "bakes": bakes,
    }


def _cache_key(target: Target):
    root = target.datablock
    return (root.as_pointer(), target.source, bpy.data.filepath)


def get_scan(context, force: bool = False) -> dict | None:
    target = resolve_target(context)
    if target is None:
        return None
    key = _cache_key(target)
    if force or _CACHE["key"] != key or _CACHE["scan"] is None:
        _CACHE["key"] = key
        _CACHE["scan"] = scan_target(target)
    return _CACHE["scan"]


def invalidate_scan() -> None:
    _CACHE["key"] = None
    _CACHE["scan"] = None


def _find_id(id_type: str, name: str):
    collections = {
        "Image": bpy.data.images,
        "VectorFont": bpy.data.fonts,
        "Object": bpy.data.objects,
    }
    collection = collections.get(id_type)
    return collection.get(name) if collection is not None else None


class NO3D_OT_stowaway_refresh(Operator):
    bl_idname = "no3d.stowaway_refresh"
    bl_label = "Refresh Payload"
    bl_description = "Rescan the active current-file datablock and its dependencies"

    def execute(self, context):
        scan = get_scan(context, force=True)
        if scan is None:
            self.report({"WARNING"}, "No current-file target in this editor")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Scanned {scan['root_name']}")
        return {"FINISHED"}


class NO3D_OT_stowaway_jump(Operator):
    bl_idname = "no3d.stowaway_jump"
    bl_label = "Jump To"
    bl_description = "Select and reveal this current-file dependency"
    bl_options = {"REGISTER"}

    target_type: StringProperty()
    target_name: StringProperty()
    node_group: StringProperty(default="")
    node_name: StringProperty(default="")

    def execute(self, context):
        if self.target_type == "Object":
            obj = bpy.data.objects.get(self.target_name)
            if obj is None:
                self.report({"ERROR"}, f"Object not found: {self.target_name}")
                return {"CANCELLED"}
            for selected in list(getattr(context, "selected_objects", ())):
                selected.select_set(False)
            obj.hide_set(False)
            obj.select_set(True)
            context.view_layer.objects.active = obj
            if getattr(context.area, "type", "") == "VIEW_3D":
                try:
                    bpy.ops.view3d.view_selected(use_all_regions=False)
                except RuntimeError:
                    pass
            self.report({"INFO"}, f"Selected {obj.name}")
            return {"FINISHED"}

        self.report({"WARNING"}, "This dependency cannot be selected in the viewport")
        return {"CANCELLED"}


class NO3D_OT_stowaway_jump_node(Operator):
    bl_idname = "no3d.stowaway_jump_node"
    bl_label = "Jump to Node"
    bl_description = "Open the retaining node group and frame the reference node"
    bl_options = {"REGISTER"}

    node_group: StringProperty()
    node_name: StringProperty()

    def execute(self, context):
        tree = bpy.data.node_groups.get(self.node_group)
        node = tree.nodes.get(self.node_name) if tree else None
        if tree is None or node is None:
            self.report({"ERROR"}, "Retaining node is no longer available")
            return {"CANCELLED"}

        for candidate in tree.nodes:
            candidate.select = False
        node.select = True
        tree.nodes.active = node

        area = context.area
        if area is None:
            return {"CANCELLED"}
        area.type = "NODE_EDITOR"
        space = area.spaces.active
        space.tree_type = tree.bl_idname
        try:
            space.pin = True
            space.node_tree = tree
        except (AttributeError, TypeError):
            self.report({"INFO"}, f"Selected {tree.name} / {node.name}; open that group to view it")
            return {"FINISHED"}
        try:
            bpy.ops.node.view_selected()
        except RuntimeError:
            pass
        return {"FINISHED"}


class NO3D_OT_pack_resource(Operator):
    bl_idname = "no3d.pack_asset_resource"
    bl_label = "Pack Resource"
    bl_description = "Embed this intentional image or font in the current .blend; save separately to persist"
    bl_options = {"REGISTER", "UNDO"}

    id_type: StringProperty()
    datablock_name: StringProperty()

    def execute(self, context):
        datablock = _find_id(self.id_type, self.datablock_name)
        if datablock is None or not hasattr(datablock, "pack"):
            self.report({"ERROR"}, "Resource is unavailable or cannot be packed")
            return {"CANCELLED"}
        try:
            datablock.pack()
        except Exception as exc:
            self.report({"ERROR"}, f"Could not pack {datablock.name}: {exc}")
            return {"CANCELLED"}
        invalidate_scan()
        self.report({"INFO"}, f"Packed {datablock.name}; save the .blend to persist it")
        return {"FINISHED"}


class NO3D_OT_pack_included_resources(Operator):
    bl_idname = "no3d.pack_included_resources"
    bl_label = "Pack Included Resources"
    bl_description = "Pack only reachable images and fonts for the active target"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scan = get_scan(context, force=True)
        if scan is None:
            return {"CANCELLED"}
        packed = 0
        errors = []
        for row in scan["resources"]:
            if row["packed"]:
                continue
            datablock = _find_id(row["id_type"], row["name"])
            if datablock is None or not hasattr(datablock, "pack"):
                errors.append(row["name"])
                continue
            try:
                datablock.pack()
                packed += 1
            except Exception:
                errors.append(row["name"])
        invalidate_scan()
        if errors:
            self.report({"WARNING"}, f"Packed {packed}; failed: {', '.join(errors[:3])}")
        else:
            self.report({"INFO"}, f"Packed {packed} included resource(s); save to persist")
        return {"FINISHED"}


def _scene_clean_preview(context):
    target = resolve_target(context)
    if target is None or not isinstance(target.datablock, bpy.types.Object):
        return None
    closure, _previous = _dependency_graph(target.datablock)
    kept_objects = {item for item in closure if isinstance(item, bpy.types.Object)}
    removed_objects = set(bpy.data.objects) - kept_objects
    extra_scenes = set(bpy.data.scenes) - {context.scene}
    return target, closure, kept_objects, removed_objects, extra_scenes


class NO3D_OT_scene_clean(Operator):
    bl_idname = "no3d.scene_clean"
    bl_label = "Scene Clean"
    bl_description = "In an isolated asset file, keep the active object dependency closure and remove unrelated scene data"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        preview = _scene_clean_preview(context)
        if preview is None:
            self.report({"WARNING"}, "Scene Clean requires an active local object")
            return {"CANCELLED"}
        return context.window_manager.invoke_confirm(self, event)

    def draw(self, context):
        preview = _scene_clean_preview(context)
        if preview is None:
            return
        target, closure, kept, removed, scenes = preview
        col = self.layout.column()
        col.label(text=f"Keep {target.datablock.name} + {len(closure) - 1} dependencies")
        col.label(text=f"Remove {len(removed)} object(s) and {len(scenes)} extra scene(s)")
        col.label(text="References are not broken; reachable dependencies remain.", icon="INFO")
        col.label(text="The file is not saved automatically.", icon="ERROR")

    def execute(self, context):
        preview = _scene_clean_preview(context)
        if preview is None:
            return {"CANCELLED"}
        _target, _closure, _kept, removed_objects, extra_scenes = preview
        removed_names = [obj.name for obj in removed_objects]
        for scene in extra_scenes:
            bpy.data.scenes.remove(scene)
        for obj in removed_objects:
            if obj.name in bpy.data.objects:
                bpy.data.objects.remove(obj, do_unlink=True)
        purged = bpy.data.orphans_purge(do_recursive=True)
        invalidate_scan()
        self.report({"INFO"}, f"Scene Clean removed {len(removed_names)} object(s); purged {purged} orphan(s)")
        return {"FINISHED"}


def _draw_counts(layout, counts: Counter):
    order = ("Object", "Mesh", "GeometryNodeTree", "Material", "Image", "VectorFont", "Collection")
    values = [(name, counts.get(name, 0)) for name in order if counts.get(name, 0)]
    for index in range(0, len(values), 2):
        row = layout.row(align=True)
        for name, count in values[index:index + 2]:
            row.label(text=f"{name}: {count}")


def draw_inspector(layout, context):
    scan = get_scan(context)
    if scan is None:
        box = layout.box()
        box.label(text="No current-file target in this editor", icon="INFO")
        box.label(text="Select an active object or Current File asset")
        return

    header = layout.box()
    row = header.row(align=True)
    row.label(text=scan["root_name"], icon="ASSET_MANAGER")
    row.operator("no3d.stowaway_refresh", text="", icon="FILE_REFRESH")
    header.label(text=f"{scan['source']} · {scan['root_type']}")

    payload = layout.box()
    payload.label(text=f"Delivery Payload · {len(scan['closure'])} datablocks", icon="PACKAGE")
    _draw_counts(payload, scan["counts"])
    duplicate_count = max(0, len(scan["asset_roots"]) - (1 if getattr(resolve_target(context).datablock, "asset_data", None) else 0))
    if duplicate_count:
        warning = payload.row()
        warning.alert = True
        warning.label(text=f"{duplicate_count} additional marked asset(s)", icon="ERROR")
    else:
        payload.label(text="No additional marked assets", icon="CHECKMARK")

    stowaways = layout.box()
    stowaways.label(text=f"Object Dependencies · {len(scan['objects'])}", icon="OUTLINER_OB_GROUP_INSTANCE")
    if not scan["objects"]:
        stowaways.label(text="No additional objects delivered", icon="CHECKMARK")
    for item in scan["objects"][:20]:
        row = stowaways.row(align=True)
        icon = "ERROR" if item["status"] == "Inactive branch" else "OBJECT_DATA"
        row.label(text=item["name"], icon=icon)
        op = row.operator("no3d.stowaway_jump", text="", icon="RESTRICT_SELECT_OFF")
        op.target_type = "Object"
        op.target_name = item["name"]
        if item["node_group"] and item["node"]:
            op = row.operator("no3d.stowaway_jump_node", text="", icon="NODETREE")
            op.node_group = item["node_group"]
            op.node_name = item["node"]
        detail = stowaways.row()
        detail.label(text=f"{item['status']} · {item['path']}")
    if len(scan["objects"]) > 20:
        stowaways.label(text=f"+ {len(scan['objects']) - 20} more; refine manually", icon="INFO")

    resources = layout.box()
    resources.label(text=f"Included Resources · {len(scan['resources'])}", icon="PACKAGE")
    unpacked = 0
    for item in scan["resources"]:
        row = resources.row(align=True)
        if item["packed"]:
            row.label(text=item["name"], icon="CHECKMARK")
            row.label(text="Packed")
        else:
            unpacked += 1
            row.label(text=item["name"], icon="FILE")
            op = row.operator("no3d.pack_asset_resource", text="Pack", icon="PACKAGE")
            op.id_type = item["id_type"]
            op.datablock_name = item["name"]
    if not scan["resources"]:
        resources.label(text="No reachable images or external fonts")
    if unpacked:
        resources.operator("no3d.pack_included_resources", icon="PACKAGE")
        resources.label(text="Save the .blend after packing", icon="INFO")

    if scan["bakes"]:
        bakes = layout.box()
        bakes.label(text=f"Geometry Nodes Bakes · {len(scan['bakes'])}", icon="GEOMETRY_NODES")
        for item in scan["bakes"]:
            bakes.label(text=f"{item['node']} · {item['target']}")
            bakes.label(text=f"{item['object']} / {item['modifier']}")
        bakes.label(text="Status only; baking is managed in the modifier", icon="INFO")

    debris = layout.box()
    debris.label(text=f"Not Delivered · {sum(scan['debris_counts'].values())} current-file datablocks", icon="GHOST_ENABLED")
    _draw_counts(debris, scan["debris_counts"])

    clean = layout.box()
    clean.label(text="Isolated Asset File", icon="BRUSH_DATA")
    if scan["root_type"] == "Object":
        clean.operator("no3d.scene_clean", text="Scene Clean", icon="BRUSH_DATA")
        clean.label(text="Keeps reachable dependencies; never saves automatically", icon="INFO")
    else:
        clean.label(text="Scene Clean requires an active object", icon="INFO")


class NO3D_PT_stowaway_inspector(Panel):
    bl_label = "Stowaway Inspector"
    bl_idname = "NO3D_PT_stowaway_inspector"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "NO3D Dev"
    bl_parent_id = "NO3D_PT_extract_v3"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        draw_inspector(self.layout, context)


class NO3D_PT_stowaway_inspector_assetbrowser(Panel):
    bl_label = "Stowaway Inspector"
    bl_idname = "NO3D_PT_stowaway_inspector_assetbrowser"
    bl_space_type = "FILE_BROWSER"
    bl_region_type = "TOOL_PROPS"
    bl_category = "NO3D Dev"
    bl_parent_id = "NO3D_PT_extract_v3_assetbrowser"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return getattr(context.space_data, "browse_mode", None) == "ASSETS"

    def draw(self, context):
        draw_inspector(self.layout, context)


_CLASSES = (
    NO3D_OT_stowaway_refresh,
    NO3D_OT_stowaway_jump,
    NO3D_OT_stowaway_jump_node,
    NO3D_OT_pack_resource,
    NO3D_OT_pack_included_resources,
    NO3D_OT_scene_clean,
    NO3D_PT_stowaway_inspector,
    NO3D_PT_stowaway_inspector_assetbrowser,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    invalidate_scan()
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
