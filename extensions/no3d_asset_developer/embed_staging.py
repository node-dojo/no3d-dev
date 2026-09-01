"""Geometry Nodes staging tools for dependency-free embedded components."""

from __future__ import annotations

import re

import bpy
from bpy.types import Operator, Panel


READER_GROUP_NAME = "NO3D Embed Reader"
EMBED_PREFIX = "no3d_embed_"


def _identifier(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (text or "").strip().lower()).strip("_")
    return EMBED_PREFIX + (slug or "component")


def _object_names(nodes) -> list[str]:
    """Return object names reachable from selected Object Info/group nodes."""
    names: list[str] = []
    seen_trees: set[int] = set()

    def visit(items):
        for node in items:
            if node.bl_idname == "GeometryNodeObjectInfo":
                socket = node.inputs.get("Object")
                obj = socket.default_value if socket else None
                if obj is not None:
                    names.append(obj.name)
            elif node.bl_idname == "GeometryNodeGroup" and node.node_tree is not None:
                pointer = node.node_tree.as_pointer()
                if pointer not in seen_trees:
                    seen_trees.add(pointer)
                    visit(node.node_tree.nodes)

    visit(nodes)
    return names


def _geometry_socket(sockets):
    return next((socket for socket in sockets if socket.type == 'GEOMETRY'), None)


def ensure_reader_group():
    group = bpy.data.node_groups.get(READER_GROUP_NAME)
    if group is not None and group.bl_idname == 'GeometryNodeTree':
        for node in group.nodes:
            if node.bl_idname == 'GeometryNodeSeparateGeometry':
                node.domain = 'POINT'
        return group

    group = bpy.data.node_groups.new(READER_GROUP_NAME, 'GeometryNodeTree')
    group.interface.new_socket(
        name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry'
    )
    name_socket = group.interface.new_socket(
        name="Attribute Name", in_out='INPUT', socket_type='NodeSocketString'
    )
    name_socket.default_value = _identifier("component")
    group.interface.new_socket(
        name="Component", in_out='OUTPUT', socket_type='NodeSocketGeometry'
    )
    group.interface.new_socket(
        name="Remainder", in_out='OUTPUT', socket_type='NodeSocketGeometry'
    )
    group.interface.new_socket(
        name="Selection", in_out='OUTPUT', socket_type='NodeSocketBool'
    )

    nodes = group.nodes
    links = group.links
    group_input = nodes.new('NodeGroupInput')
    group_input.location = (-420, 0)
    named = nodes.new('GeometryNodeInputNamedAttribute')
    named.data_type = 'BOOLEAN'
    named.location = (-420, -160)
    separate = nodes.new('GeometryNodeSeparateGeometry')
    separate.domain = 'POINT'
    separate.location = (-100, 20)
    group_output = nodes.new('NodeGroupOutput')
    group_output.location = (180, 20)

    links.new(group_input.outputs["Geometry"], separate.inputs["Geometry"])
    links.new(group_input.outputs["Attribute Name"], named.inputs["Name"])
    links.new(named.outputs["Attribute"], separate.inputs["Selection"])
    links.new(separate.outputs["Selection"], group_output.inputs["Component"])
    links.new(separate.outputs["Inverted"], group_output.inputs["Remainder"])
    links.new(named.outputs["Attribute"], group_output.inputs["Selection"])
    return group


def finish_staged_group(group_node, attribute_name: str):
    """Add the standardized attribute tail and companion reader node."""
    group = group_node.node_tree
    group.name = f"STAGE — {attribute_name.removeprefix(EMBED_PREFIX).replace('_', ' ')}"

    name_socket = group.interface.new_socket(
        name="Embed Name", in_out='INPUT', socket_type='NodeSocketString'
    )
    name_socket.default_value = attribute_name
    group_node.inputs["Embed Name"].default_value = attribute_name

    group_output = next(n for n in group.nodes if n.bl_idname == 'NodeGroupOutput')
    group_input = next(
        (n for n in group.nodes if n.bl_idname == 'NodeGroupInput'),
        None,
    )
    if group_input is None:
        group_input = group.nodes.new('NodeGroupInput')
        group_input.location = (group_output.location.x - 440, group_output.location.y - 180)
    geometry_input = _geometry_socket(group_output.inputs)
    if geometry_input is None or not geometry_input.is_linked:
        raise RuntimeError("The selected branch has no connected Geometry output")

    prior_link = geometry_input.links[0]
    prior_socket = prior_link.from_socket
    group.links.remove(prior_link)

    store = group.nodes.new('GeometryNodeStoreNamedAttribute')
    store.data_type = 'BOOLEAN'
    store.domain = 'POINT'
    store.inputs["Value"].default_value = True
    store.location = (group_output.location.x - 220, group_output.location.y)
    group.links.new(prior_socket, store.inputs["Geometry"])
    group.links.new(group_input.outputs["Embed Name"], store.inputs["Name"])
    group.links.new(store.outputs["Geometry"], geometry_input)

    parent_tree = group_node.id_data
    reader = parent_tree.nodes.new('GeometryNodeGroup')
    reader.node_tree = ensure_reader_group()
    reader.inputs["Attribute Name"].default_value = attribute_name
    reader.location = (
        group_node.location.x + max(group_node.width, 140.0) + 80.0,
        group_node.location.y,
    )
    return store, reader


def _selected_stage(context):
    tree = getattr(context.space_data, "edit_tree", None)
    if tree is None:
        return None
    stages = [
        node for node in tree.nodes
        if node.select
        and node.bl_idname == 'GeometryNodeGroup'
        and node.node_tree is not None
        and node.node_tree.name.startswith("STAGE —")
        and node.inputs.get("Embed Name") is not None
    ]
    return stages[0] if len(stages) == 1 else None


def _normalize_stage_domain(stage_node):
    for node in stage_node.node_tree.nodes:
        if node.bl_idname == 'GeometryNodeStoreNamedAttribute':
            node.domain = 'POINT'


def _active_geometry_object(context):
    obj = context.active_object
    if obj is None or obj.type != 'MESH' or context.mode != 'OBJECT':
        return None
    return obj


def _geometry_modifier_for_tree(obj, tree):
    return next(
        (
            modifier for modifier in obj.modifiers
            if modifier.type == 'NODES' and modifier.node_group == tree
        ),
        None,
    )


def _evaluate_stage_mesh(context, obj, parent_tree, stage_node):
    """Evaluate only one stage while preserving its complete parent-tree context."""
    temporary_tree = parent_tree.copy()
    temporary_tree.name = f"TEMP BAKE — {stage_node.node_tree.name}"
    copied_stage = temporary_tree.nodes.get(stage_node.name)
    if copied_stage is None:
        bpy.data.node_groups.remove(temporary_tree)
        raise RuntimeError("The selected stage was not preserved in the bake copy")

    group_output = next(
        (node for node in temporary_tree.nodes if node.bl_idname == 'NodeGroupOutput'),
        None,
    )
    geometry_input = _geometry_socket(group_output.inputs) if group_output else None
    geometry_output = _geometry_socket(copied_stage.outputs)
    if geometry_input is None or geometry_output is None:
        bpy.data.node_groups.remove(temporary_tree)
        raise RuntimeError("The stage or modifier tree has no Geometry output")
    for link in list(geometry_input.links):
        temporary_tree.links.remove(link)
    temporary_tree.links.new(geometry_output, geometry_input)

    temporary_object = obj.copy()
    temporary_object.data = obj.data.copy()
    temporary_object.name = "TEMP NO3D EMBED BAKE"
    collection = obj.users_collection[0] if obj.users_collection else context.scene.collection
    collection.objects.link(temporary_object)
    for modifier in list(temporary_object.modifiers):
        temporary_object.modifiers.remove(modifier)
    modifier = temporary_object.modifiers.new("TEMP NO3D EMBED BAKE", 'NODES')
    modifier.node_group = temporary_tree

    try:
        context.view_layer.update()
        depsgraph = context.evaluated_depsgraph_get()
        evaluated = temporary_object.evaluated_get(depsgraph)
        baked_mesh = bpy.data.meshes.new_from_object(
            evaluated,
            preserve_all_data_layers=True,
            depsgraph=depsgraph,
        )
        baked_mesh.name = f"BAKED — {stage_node.node_tree.name.removeprefix('STAGE — ')}"
        return baked_mesh
    finally:
        temporary_mesh = temporary_object.data
        bpy.data.objects.remove(temporary_object, do_unlink=True)
        if temporary_mesh.users == 0:
            bpy.data.meshes.remove(temporary_mesh)
        bpy.data.node_groups.remove(temporary_tree, do_unlink=True)


def _combined_parent_mesh(context, parent, baked_mesh):
    """Return a new mesh containing parent base data plus the baked component."""
    piece = bpy.data.objects.new("TEMP NO3D EMBED PIECE", baked_mesh)
    collection = parent.users_collection[0] if parent.users_collection else context.scene.collection
    collection.objects.link(piece)
    piece.matrix_world = parent.matrix_world.copy()

    join_tree = bpy.data.node_groups.new("TEMP NO3D EMBED COMBINE", 'GeometryNodeTree')
    join_tree.interface.new_socket(
        name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry'
    )
    join_tree.interface.new_socket(
        name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry'
    )
    group_input = join_tree.nodes.new('NodeGroupInput')
    object_info = join_tree.nodes.new('GeometryNodeObjectInfo')
    object_info.inputs["Object"].default_value = piece
    join = join_tree.nodes.new('GeometryNodeJoinGeometry')
    group_output = join_tree.nodes.new('NodeGroupOutput')
    join_tree.links.new(group_input.outputs["Geometry"], join.inputs["Geometry"])
    join_tree.links.new(object_info.outputs["Geometry"], join.inputs["Geometry"])
    join_tree.links.new(join.outputs["Geometry"], group_output.inputs["Geometry"])

    temporary = parent.copy()
    temporary.data = parent.data.copy()
    temporary.name = "TEMP NO3D EMBED PARENT"
    collection.objects.link(temporary)
    for modifier in list(temporary.modifiers):
        temporary.modifiers.remove(modifier)
    modifier = temporary.modifiers.new("TEMP NO3D EMBED COMBINE", 'NODES')
    modifier.node_group = join_tree
    try:
        context.view_layer.update()
        depsgraph = context.evaluated_depsgraph_get()
        evaluated = temporary.evaluated_get(depsgraph)
        combined = bpy.data.meshes.new_from_object(
            evaluated,
            preserve_all_data_layers=True,
            depsgraph=depsgraph,
        )
        combined.name = f"{parent.data.name} — embedded"
        return combined
    finally:
        temporary_mesh = temporary.data
        bpy.data.objects.remove(temporary, do_unlink=True)
        bpy.data.objects.remove(piece, do_unlink=True)
        if temporary_mesh.users == 0:
            bpy.data.meshes.remove(temporary_mesh)
        bpy.data.node_groups.remove(join_tree, do_unlink=True)


def _evaluated_signature(context, obj):
    context.view_layer.update()
    depsgraph = context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        counts = (len(mesh.vertices), len(mesh.edges), len(mesh.polygons))
        if mesh.vertices:
            coordinates = [vertex.co for vertex in mesh.vertices]
            bounds = tuple(
                round(value, 5)
                for axis in range(3)
                for value in (
                    min(coordinate[axis] for coordinate in coordinates),
                    max(coordinate[axis] for coordinate in coordinates),
                )
            )
        else:
            bounds = ()
        return counts, bounds
    finally:
        evaluated.to_mesh_clear()


def _preflight_baked_replacement(
    context, parent, parent_tree, stage_node, reader_node, combined_mesh
):
    simulation_tree = parent_tree.copy()
    simulation_tree.name = f"TEMP PREFLIGHT — {stage_node.node_tree.name}"
    copied_stage = simulation_tree.nodes.get(stage_node.name)
    copied_reader = simulation_tree.nodes.get(reader_node.name)
    component = copied_reader.outputs.get("Component") if copied_reader else None
    destinations = [
        (link.to_node, link.to_socket)
        for socket in copied_stage.outputs
        if socket.type == 'GEOMETRY'
        for link in list(socket.links)
    ]
    if component is None:
        bpy.data.node_groups.remove(simulation_tree, do_unlink=True)
        raise RuntimeError("The matching Embed Reader has no Component output")
    for target_node, target_socket in destinations:
        simulation_tree.links.new(component, target_socket)
    for socket in copied_stage.outputs:
        for link in list(socket.links):
            simulation_tree.links.remove(link)

    simulation = parent.copy()
    simulation.data = combined_mesh.copy()
    simulation.name = "TEMP NO3D EMBED PREFLIGHT"
    collection = parent.users_collection[0] if parent.users_collection else context.scene.collection
    collection.objects.link(simulation)
    for modifier in list(simulation.modifiers):
        simulation.modifiers.remove(modifier)
    modifier = simulation.modifiers.new("TEMP NO3D EMBED PREFLIGHT", 'NODES')
    modifier.node_group = simulation_tree
    try:
        return _evaluated_signature(context, simulation)
    finally:
        simulation_mesh = simulation.data
        bpy.data.objects.remove(simulation, do_unlink=True)
        if simulation_mesh.users == 0:
            bpy.data.meshes.remove(simulation_mesh)
        bpy.data.node_groups.remove(simulation_tree, do_unlink=True)


def _copy_reader_at_stage(tree, source_reader, stage_node):
    """Create a reader instance without disturbing an already-wired reader."""
    replacement = tree.nodes.new('GeometryNodeGroup')
    replacement.node_tree = source_reader.node_tree
    replacement.location = stage_node.location.copy()
    replacement.parent = stage_node.parent
    replacement.width = source_reader.width

    for source_input in source_reader.inputs:
        target_input = replacement.inputs.get(source_input.name)
        if target_input is None:
            continue
        if hasattr(source_input, "default_value") and hasattr(target_input, "default_value"):
            target_input.default_value = source_input.default_value
        for link in source_input.links:
            tree.links.new(link.from_socket, target_input)
    return replacement


class NO3D_AD_OT_stage_embed(Operator):
    """Package selected Geometry Nodes as a named, bake-ready embed stage"""

    bl_idname = "no3d_asset_developer.stage_embed"
    bl_label = "Stage Embed"
    bl_description = (
        "Group selected nodes, store an inferred component attribute at the "
        "output, and place a matching Embed Reader beside it"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        space = context.space_data
        tree = getattr(space, "edit_tree", None)
        return (
            context.area is not None
            and context.area.type == 'NODE_EDITOR'
            and tree is not None
            and tree.bl_idname == 'GeometryNodeTree'
            and any(node.select for node in tree.nodes)
        )

    def execute(self, context):
        parent_tree = context.space_data.edit_tree
        selected = [node for node in parent_tree.nodes if node.select]
        source_names = _object_names(selected)
        fallback = selected[0].node_tree.name if (
            len(selected) == 1
            and selected[0].bl_idname == 'GeometryNodeGroup'
            and selected[0].node_tree is not None
        ) else "component"
        attribute_name = _identifier(source_names[0] if source_names else fallback)

        before = {node.as_pointer() for node in parent_tree.nodes}
        result = bpy.ops.node.group_make()
        if 'FINISHED' not in result:
            self.report({'ERROR'}, "Blender could not group the selected nodes")
            return {'CANCELLED'}

        group_node = next(
            (
                node for node in parent_tree.nodes
                if node.as_pointer() not in before
                and node.bl_idname == 'GeometryNodeGroup'
            ),
            None,
        )
        if group_node is None:
            self.report({'ERROR'}, "Could not locate the new staged group")
            return {'CANCELLED'}

        # Native group_make enters the new group. Return to the parent before
        # placing the reader beside the new group node.
        if context.space_data.edit_tree == group_node.node_tree:
            bpy.ops.node.tree_path_parent()

        try:
            _store, reader = finish_staged_group(group_node, attribute_name)
        except Exception as exc:
            self.report({'ERROR'}, f"Could not finish embed stage: {exc}")
            return {'CANCELLED'}

        for node in parent_tree.nodes:
            node.select = False
        group_node.select = True
        reader.select = True
        parent_tree.nodes.active = reader
        self.report({'INFO'}, f"Staged {attribute_name}; reader placed beside it")
        return {'FINISHED'}


class NO3D_AD_OT_bake_embed(Operator):
    """Bake one selected staged component into the active object's base mesh"""

    bl_idname = "no3d_asset_developer.bake_embed"
    bl_label = "Bake Staged to Embed"
    bl_description = (
        "Evaluate the selected Stage group, join its attributed result into "
        "the active mesh, and disconnect the procedural stage"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        space = context.space_data
        tree = getattr(space, "edit_tree", None)
        obj = _active_geometry_object(context)
        return (
            context.area is not None
            and context.area.type == 'NODE_EDITOR'
            and tree is not None
            and tree.bl_idname == 'GeometryNodeTree'
            and obj is not None
            and _geometry_modifier_for_tree(obj, tree) is not None
            and _selected_stage(context) is not None
        )

    def execute(self, context):
        obj = _active_geometry_object(context)
        tree = context.space_data.edit_tree
        stage = _selected_stage(context)
        if obj is None or stage is None:
            self.report({'ERROR'}, "Select exactly one Stage group on an active mesh object")
            return {'CANCELLED'}

        attribute_name = stage.inputs["Embed Name"].default_value.strip()
        if not attribute_name:
            self.report({'ERROR'}, "The selected Stage has no Embed Name")
            return {'CANCELLED'}
        readers = [
            node for node in tree.nodes
            if node.bl_idname == 'GeometryNodeGroup'
            and node.node_tree is not None
            and node.node_tree.name == READER_GROUP_NAME
            and node.inputs.get("Attribute Name") is not None
            and node.inputs["Attribute Name"].default_value == attribute_name
        ]
        if not readers:
            self.report({'ERROR'}, f"No matching Embed Reader for {attribute_name}")
            return {'CANCELLED'}

        try:
            _normalize_stage_domain(stage)
            ensure_reader_group()
            before_signature = _evaluated_signature(context, obj)
            baked_mesh = _evaluate_stage_mesh(context, obj, tree, stage)
            attribute = baked_mesh.attributes.get(attribute_name)
            if attribute is None or attribute.data_type != 'BOOLEAN' or attribute.domain != 'POINT':
                bpy.data.meshes.remove(baked_mesh)
                raise RuntimeError(f"Baked result is missing point attribute {attribute_name}")
            tagged_points = sum(1 for value in attribute.data if value.value)
            if tagged_points == 0:
                bpy.data.meshes.remove(baked_mesh)
                raise RuntimeError(f"Baked result contains no points tagged {attribute_name}")

            combined_mesh = _combined_parent_mesh(context, obj, baked_mesh)
            bpy.data.meshes.remove(baked_mesh)
            after_signature = _preflight_baked_replacement(
                context, obj, tree, stage, readers[0], combined_mesh
            )
            if after_signature != before_signature:
                self.report(
                    {'WARNING'},
                    "Bake changes evaluated geometry; committed because reader "
                    "integration is artist-directed"
                )

            previous_mesh = obj.data
            obj.data = combined_mesh
            source_reader = readers[0]
            stage_destinations = [
                (link.to_node, link.to_socket)
                for socket in stage.outputs
                if socket.type == 'GEOMETRY'
                for link in list(socket.links)
            ]
            stage_location = stage.location.copy()
            for socket in stage.outputs:
                for link in list(socket.links):
                    tree.links.remove(link)
            reader = _copy_reader_at_stage(tree, source_reader, stage)
            component_output = reader.outputs.get("Component")
            for target_node, target_socket in stage_destinations:
                tree.links.new(component_output, target_socket)
            stage.location = (
                stage_location.x,
                stage_location.y + max(stage.height + 80.0, 180.0),
            )
            stage["no3d_embed_baked"] = True
            stage.use_custom_color = True
            stage.color = (0.18, 0.18, 0.18)

            for node in tree.nodes:
                node.select = False
            stage.select = True
            reader.select = True
            tree.nodes.active = reader
            context.view_layer.update()
            if previous_mesh.users == 0:
                # Retain the pre-bake carrier as an undo/recovery datablock.
                previous_mesh.name = f"RECOVERY — {previous_mesh.name}"
        except Exception as exc:
            self.report({'ERROR'}, f"Embed bake failed: {exc}")
            return {'CANCELLED'}

        self.report(
            {'INFO'},
            f"Baked {attribute_name}: {tagged_points} tagged points joined; stage disconnected",
        )
        return {'FINISHED'}


class NO3D_AD_PT_embed_staging(Panel):
    bl_label = "Embed Staging"
    bl_idname = "NO3D_AD_PT_embed_staging"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "NO3D Dev"

    @classmethod
    def poll(cls, context):
        tree = getattr(context.space_data, "edit_tree", None)
        return tree is not None and tree.bl_idname == 'GeometryNodeTree'

    def draw(self, _context):
        layout = self.layout
        layout.operator(
            "no3d_asset_developer.stage_embed",
            text="Stage Embed",
            icon='NODETREE',
        )
        layout.label(text="Select a component branch, then stage it.", icon='INFO')
        layout.separator()
        layout.operator(
            "no3d_asset_developer.bake_embed",
            text="Bake Staged to Embed",
            icon='MODIFIER',
        )
        layout.label(text="Select one staged group to bake.", icon='INFO')


_CLASSES = (
    NO3D_AD_OT_stage_embed,
    NO3D_AD_OT_bake_embed,
    NO3D_AD_PT_embed_staging,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
