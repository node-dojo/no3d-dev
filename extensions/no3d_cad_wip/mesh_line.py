"""Fast two-point mesh-line creation and its F-Tool variant."""

from __future__ import annotations

import uuid

import bpy
from bpy.props import BoolProperty
from bpy.types import Operator

from . import ids
from .contexts import active_geometry_nodes_modifier
from .generic_ftool import (
    INSTANCE_KEY,
    ROLE_KEY,
    TOOL_KEY,
    _embed_group,
    _reference_group,
)
from .split_with_plane import _active_geometry_output, _socket


def _create_line_object(context, name="Mesh Line"):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(0.0, 0.0, 0.0), (0.0, 0.0, 0.0)], [(0, 1)], [])
    mesh.vertices[0].select = False
    mesh.vertices[1].select = True
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    context.collection.objects.link(obj)
    obj.location = context.scene.cursor.location.copy()
    for selected in tuple(context.selected_objects):
        selected.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    return obj


def _ensure_geometry_nodes_modifier(owner):
    modifier = active_geometry_nodes_modifier(owner)
    if modifier is not None:
        return modifier
    tree = bpy.data.node_groups.new(f"{owner.name} Geometry Nodes", "GeometryNodeTree")
    tree.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    group_input = tree.nodes.new("NodeGroupInput")
    group_output = tree.nodes.new("NodeGroupOutput")
    group_input.location = (-200.0, 0.0)
    group_output.location = (200.0, 0.0)
    tree.links.new(group_input.outputs["Geometry"], group_output.inputs["Geometry"])
    modifier = owner.modifiers.new("GeometryNodes", "NODES")
    modifier.node_group = tree
    return modifier


def _begin_endpoint_placement(context, obj):
    bpy.ops.object.mode_set(mode="EDIT")
    context.tool_settings.mesh_select_mode = (True, False, False)
    region = next((item for item in context.area.regions if item.type == "WINDOW"), None)
    if region is None:
        return False
    with context.temp_override(area=context.area, region=region):
        bpy.ops.transform.translate("INVOKE_DEFAULT")
    return True


def _bind_as_feature(owner, reference):
    instance_id = str(uuid.uuid4())
    reference[TOOL_KEY] = "no3d.mesh-line"
    reference[INSTANCE_KEY] = instance_id
    reference[ROLE_KEY] = "reference"
    bpy.context.view_layer.update()
    world = reference.matrix_world.copy()
    reference.parent = owner
    reference.matrix_world = world
    modifier = reference.modifiers.new("F-Tool Reference", "NODES")
    modifier.node_group = _reference_group(ids.GENERIC_REFERENCE_GROUP)

    owner_modifier = _ensure_geometry_nodes_modifier(owner)
    tree = owner_modifier.node_group
    embed_node = tree.nodes.new("GeometryNodeGroup")
    embed_node.node_tree = _embed_group(ids.GENERIC_EMBED_GROUP)
    embed_node.label = "Mesh Line F-Tool"
    output = _active_geometry_output(tree)
    embed_node.location = (
        (output.location.x - 220.0, output.location.y - 180.0)
        if output is not None else (0.0, 0.0)
    )
    embed_node[TOOL_KEY] = "no3d.mesh-line"
    embed_node[INSTANCE_KEY] = instance_id
    embed_node[ROLE_KEY] = "embed"
    object_input = _socket(embed_node.inputs, "Object")
    if object_input is None:
        raise RuntimeError("The configured F-Tool Embed definition has no Object input")
    object_input.default_value = reference
    return embed_node


def _selected_feature_owner(context):
    owner = context.active_object
    if owner is None or not owner.select_get():
        return None
    return owner


def _set_target_prompt(context, enabled):
    context.workspace.status_text_set(
        "Click an object to use as the F-Tool target · Esc to cancel"
        if enabled else None
    )
    if enabled:
        context.window.cursor_modal_set("EYEDROPPER")
    else:
        context.window.cursor_modal_restore()


class NO3D_CAD_OT_add_mesh_line(Operator):
    """Create an anchored mesh edge and begin placing its endpoint"""

    bl_idname = ids.ADD_MESH_LINE_OT
    bl_label = "Add Mesh Line"
    bl_description = "Add an anchored mesh point and begin placing its connected endpoint"
    bl_options = {"REGISTER", "UNDO"}

    begin_placement: BoolProperty(default=True, options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and context.area is not None and context.area.type == "VIEW_3D"

    def execute(self, context):
        line = _create_line_object(context)
        if self.begin_placement:
            _begin_endpoint_placement(context, line)
        return {"FINISHED"}


class NO3D_CAD_OT_add_mesh_line_feature(Operator):
    """Create a mesh-line reference and bind it into the selected owner's graph"""

    bl_idname = ids.ADD_MESH_LINE_FEATURE_OT
    bl_label = "Add Mesh Line as F-Tool"
    bl_description = "Create an interactive mesh line parented and bound as an F-Tool reference"
    bl_options = {"REGISTER", "UNDO"}

    begin_placement: BoolProperty(default=True, options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and context.area is not None and context.area.type == "VIEW_3D"

    def invoke(self, context, event):
        if _selected_feature_owner(context) is not None:
            return self.execute(context)
        self.report({"INFO"}, "Click an object to use as the F-Tool target")
        _set_target_prompt(context, True)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"}:
            _set_target_prompt(context, False)
            return {"CANCELLED"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            bpy.ops.view3d.select(
                location=(event.mouse_region_x, event.mouse_region_y),
                deselect_all=True,
            )
            if _selected_feature_owner(context) is None:
                self.report({"WARNING"}, "Choose an object that can receive modifiers")
                return {"RUNNING_MODAL"}
            _set_target_prompt(context, False)
            return self.execute(context)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        owner = _selected_feature_owner(context)
        if owner is None:
            self.report({"ERROR"}, "No valid F-Tool target is selected")
            return {"CANCELLED"}
        line = None
        try:
            line = _create_line_object(context, "F-Tool Mesh Line")
            _bind_as_feature(owner, line)
        except Exception as exc:
            if line is not None:
                mesh = line.data
                bpy.data.objects.remove(line, do_unlink=True)
                if mesh.users == 0:
                    bpy.data.meshes.remove(mesh)
            self.report({"ERROR"}, f"Could not create Mesh Line F-Tool: {exc}")
            return {"CANCELLED"}
        if self.begin_placement:
            _begin_endpoint_placement(context, line)
        return {"FINISHED"}


CLASSES = (NO3D_CAD_OT_add_mesh_line, NO3D_CAD_OT_add_mesh_line_feature)
