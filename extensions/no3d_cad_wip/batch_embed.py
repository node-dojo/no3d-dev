"""Single and batch embedding of selected View Layer objects as F-Tools."""

from __future__ import annotations

import uuid

import bpy
from bpy.props import BoolProperty, EnumProperty
from bpy.types import Operator

from . import ids
from .generic_ftool import INSTANCE_KEY, ROLE_KEY, TOOL_KEY, _embed_group, _reachable_geometry_trees
from .mesh_line import _ensure_geometry_nodes_modifier
from .promote_inputs import promote_node_object_inputs, promote_root_node_object_inputs
from .split_with_plane import _socket


PRESENTATION_ITEMS = (
    ("HIDDEN", "Hidden in Viewport", "Hide feature objects in the viewport"),
    ("BOUNDS", "Bounds", "Show feature objects as bounding boxes"),
    ("WIRE", "Wire", "Show feature objects as wireframes"),
    ("SOLID", "Solid", "Show feature objects normally"),
    ("UNCHANGED", "Unchanged", "Preserve current viewport presentation"),
)


def selected_owner_and_features(context):
    owner = context.active_object
    if owner is None or not owner.select_get():
        return None, []
    # context.selected_objects is filtered by the invoking 3D View. In Local
    # View it can omit objects that remain selected in the Outliner and View
    # Layer, making the same visible selection behave differently by mouse
    # position. The F-Tool contract is intentionally View Layer-wide.
    return owner, [
        obj for obj in context.view_layer.objects
        if obj != owner and obj.select_get()
    ]


def _set_presentation(obj, presentation):
    if presentation == "UNCHANGED":
        return
    if presentation == "HIDDEN":
        obj.hide_set(True)
        return
    obj.hide_set(False)
    obj.display_type = {
        "BOUNDS": "BOUNDS",
        "WIRE": "WIRE",
        "SOLID": "TEXTURED",
    }[presentation]


def _parent_preserve_world(owner, obj):
    bpy.context.view_layer.update()
    world = obj.matrix_world.copy()
    obj.parent = owner
    obj.matrix_world = world


def _is_already_embedded(tree, obj):
    for reachable in _reachable_geometry_trees(tree):
        for node in reachable.nodes:
            if node.bl_idname != "GeometryNodeGroup":
                continue
            for socket in node.inputs:
                if getattr(socket, "type", None) == "OBJECT" and socket.default_value == obj:
                    return True
    return False


def _bind_embed_node(node, obj, instance_id):
    node.node_tree = _embed_group(ids.GENERIC_EMBED_GROUP)
    node[TOOL_KEY] = "no3d.embed-existing"
    node[INSTANCE_KEY] = instance_id
    node[ROLE_KEY] = "embed"
    object_input = _socket(node.inputs, "Object")
    geometry_output = _socket(node.outputs, "Geometry")
    if object_input is None or geometry_output is None:
        raise RuntimeError("F-Tool Embed must provide Object input and Geometry output")
    object_input.default_value = obj
    return geometry_output


def _node_size(node):
    width = max(float(getattr(node, "width", 140.0)), 220.0)
    measured_height = float(getattr(node, "dimensions", (0.0, 0.0))[1])
    estimated_height = 70.0 + 24.0 * max(len(node.inputs), len(node.outputs))
    return width, max(measured_height, estimated_height, 100.0)


def _node_rect(node, location=None, padding=36.0):
    x, y = location if location is not None else node.location
    width, height = _node_size(node)
    return (x - padding, y - height - padding, x + width + padding, y + padding)


def _overlaps(left, right):
    return not (
        left[2] <= right[0] or left[0] >= right[2]
        or left[3] <= right[1] or left[1] >= right[3]
    )


def _visible_editor_center(context, tree):
    screen = getattr(context, "screen", None)
    for area in screen.areas if screen is not None else ():
        if area.type != "NODE_EDITOR":
            continue
        space = area.spaces.active
        if getattr(space, "edit_tree", None) != tree:
            continue
        region = next((item for item in area.regions if item.type == "WINDOW"), None)
        if region is None:
            continue
        return region.view2d.region_to_view(region.width * 0.5, region.height * 0.5)
    return None


def _graph_center(tree, ignored):
    nodes = [node for node in tree.nodes if node != ignored and node.parent is None]
    if not nodes:
        return (0.0, 0.0)
    min_x = min(node.location.x for node in nodes)
    max_x = max(node.location.x + _node_size(node)[0] for node in nodes)
    min_y = min(node.location.y - _node_size(node)[1] for node in nodes)
    max_y = max(node.location.y for node in nodes)
    return ((min_x + max_x) * 0.5, (min_y + max_y) * 0.5)


def _place_without_overlap(context, tree, node):
    center = _visible_editor_center(context, tree) or _graph_center(tree, node)
    width, height = _node_size(node)
    base = (center[0] - width * 0.5, center[1] + height * 0.5)
    occupied = [
        _node_rect(other)
        for other in tree.nodes
        if other != node and other.parent is None
    ]
    candidates = [base]
    for ring in range(1, 13):
        for dx in range(-ring, ring + 1):
            for dy in range(-ring, ring + 1):
                if max(abs(dx), abs(dy)) != ring:
                    continue
                candidates.append((base[0] + dx * 280.0, base[1] + dy * 190.0))
    candidates.sort(key=lambda point: (point[0] - base[0]) ** 2 + (point[1] - base[1]) ** 2)
    for location in candidates:
        if not any(_overlaps(_node_rect(node, location), rect) for rect in occupied):
            node.location = location
            return location
    node.location = candidates[-1]
    return tuple(node.location)


def _create_single(context, tree, owner, obj):
    instance_id = str(uuid.uuid4())
    node = tree.nodes.new("GeometryNodeGroup")
    node.label = "F-Tool"
    _bind_embed_node(node, obj, instance_id)
    _place_without_overlap(context, tree, node)
    obj[TOOL_KEY] = "no3d.embed-existing"
    obj[INSTANCE_KEY] = instance_id
    obj[ROLE_KEY] = "reference"
    obj["no3d_feature_owner"] = owner.name
    return node


def _create_batch(context, tree, owner, objects):
    batch_id = str(uuid.uuid4())
    group = bpy.data.node_groups.new(f"{owner.name} · F-Tool Set", "GeometryNodeTree")
    group[TOOL_KEY] = "no3d.embed-existing-batch"
    group[INSTANCE_KEY] = batch_id
    group[ROLE_KEY] = "batch-definition"
    for _obj in objects:
        group.interface.new_socket(name="Object", in_out="INPUT", socket_type="NodeSocketObject")
    group.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    group_input = group.nodes.new("NodeGroupInput")
    join = group.nodes.new("GeometryNodeJoinGeometry")
    group_output = group.nodes.new("NodeGroupOutput")
    group_input.location = (-480.0, 0.0)
    join.location = (160.0, 0.0)
    group_output.location = (380.0, 0.0)
    group.links.new(join.outputs["Geometry"], group_output.inputs["Geometry"])

    instance_ids = []
    for index, obj in enumerate(objects):
        instance_id = str(uuid.uuid4())
        instance_ids.append(instance_id)
        embed = group.nodes.new("GeometryNodeGroup")
        embed.location = (-180.0, -index * 130.0)
        geometry = _bind_embed_node(embed, obj, instance_id)
        group.links.new(group_input.outputs[index], embed.inputs["Object"])
        group.links.new(geometry, join.inputs["Geometry"])
        obj[TOOL_KEY] = "no3d.embed-existing"
        obj[INSTANCE_KEY] = instance_id
        obj[ROLE_KEY] = "reference"
        obj["no3d_feature_owner"] = owner.name
        obj["no3d_ftool_batch_id"] = batch_id

    outer = tree.nodes.new("GeometryNodeGroup")
    outer.node_tree = group
    outer.label = "F-Tool Set"
    outer[TOOL_KEY] = "no3d.embed-existing-batch"
    outer[INSTANCE_KEY] = batch_id
    outer[ROLE_KEY] = "batch-embed"
    for index, obj in enumerate(objects):
        outer.inputs[index].default_value = obj
    _place_without_overlap(context, tree, outer)
    return outer, group


def embed_selected(context, presentation, required_count=None):
    owner, features = selected_owner_and_features(context)
    if owner is None:
        raise ValueError("Select feature objects and make their target the active object")
    if required_count == 1 and len(features) != 1:
        raise ValueError("Select exactly one feature object plus the active target")
    if required_count == 2 and len(features) < 2:
        raise ValueError("Select two or more feature objects plus the active target")
    if not features:
        raise ValueError("Select at least one feature object plus the active target")

    modifier = _ensure_geometry_nodes_modifier(owner)
    tree = modifier.node_group
    features = [obj for obj in features if not _is_already_embedded(tree, obj)]
    if not features:
        raise ValueError("All selected feature objects are already embedded in this target")

    for obj in features:
        _parent_preserve_world(owner, obj)
    result = (
        _create_single(context, tree, owner, features[0])
        if len(features) == 1
        else _create_batch(context, tree, owner, features)
    )
    for obj in features:
        _set_presentation(obj, presentation)
    owner.hide_set(False)
    owner.select_set(True)
    context.view_layer.objects.active = owner
    return owner, features, result


class _EmbedBase:
    presentation: EnumProperty(
        name="Feature Display",
        description="Viewport presentation applied to embedded feature objects",
        items=PRESENTATION_ITEMS,
        default="HIDDEN",
    )
    expose_objects_in_modifier: BoolProperty(
        name="Expose Objects in Modifier",
        description="Promote embedded Object inputs to the target modifier while preserving their assignments",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return (
            context.mode == "OBJECT"
            and context.area is not None
            and context.area.type == "VIEW_3D"
            and context.active_object is not None
        )

    def _execute(self, context, required_count=None):
        try:
            owner, features, result = embed_selected(context, self.presentation, required_count)
            if self.expose_objects_in_modifier:
                node = result if not isinstance(result, tuple) else result[0]
                tree = node.id_data
                area = next(
                    (
                        area for area in context.screen.areas
                        if area.type == "NODE_EDITOR"
                        and getattr(area.spaces.active, "edit_tree", None) == tree
                    ),
                    None,
                )
                if area is not None:
                    region = next(item for item in area.regions if item.type == "WINDOW")
                    with context.temp_override(area=area, region=region):
                        promote_node_object_inputs(bpy.context, node)
                else:
                    modifier = next(
                        (
                            item for item in owner.modifiers
                            if item.type == "NODES" and item.node_group == tree
                        ),
                        None,
                    )
                    promote_root_node_object_inputs(tree, node, modifier)
        except (ValueError, RuntimeError) as exc:
            self.report({"WARNING"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Embedded {len(features)} F-Tool object(s) into {owner.name}")
        return {"FINISHED"}


class NO3D_CAD_OT_embed_selected_ftools(_EmbedBase, Operator):
    bl_idname = ids.EMBED_SELECTED_FTOOLS_OT
    bl_label = "Embed Selected as F-Tools"
    bl_description = "Parent and embed selected feature objects into the active target"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return self._execute(context)


class NO3D_CAD_OT_embed_single_ftool(_EmbedBase, Operator):
    bl_idname = ids.EMBED_SINGLE_FTOOL_OT
    bl_label = "Embed Single F-Tool"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return self._execute(context, 1)


class NO3D_CAD_OT_embed_batch_ftools(_EmbedBase, Operator):
    bl_idname = ids.EMBED_BATCH_FTOOLS_OT
    bl_label = "Embed Batch F-Tools"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return self._execute(context, 2)


def draw_view3d_actions(layout):
    layout.operator(ids.EMBED_SELECTED_FTOOLS_OT, icon="CON_CHILDOF")


CLASSES = (
    NO3D_CAD_OT_embed_selected_ftools,
    NO3D_CAD_OT_embed_single_ftool,
    NO3D_CAD_OT_embed_batch_ftools,
)
