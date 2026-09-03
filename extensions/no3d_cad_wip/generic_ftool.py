"""Minimal, node-group-swappable F-Tool scaffold."""

from __future__ import annotations

import uuid

import bpy
from mathutils import Vector
from bpy.types import Operator
from bpy.props import EnumProperty, StringProperty

from . import ids
from .contexts import (
    edited_geometry_tree,
    geometry_owner_from_context,
    node_cursor_location,
    object_from_context,
)
from .feature_tools import FeatureToolSpec, invoke_search_popup
from .split_with_plane import _active_geometry_nodes_modifier, _active_geometry_output, _socket


INSTANCE_KEY = "no3d_ftool_instance_id"
ROLE_KEY = "no3d_ftool_role"
TOOL_KEY = "no3d_feature_tool"

FEATURE_TOOL_SPEC = FeatureToolSpec(
    id="generic",
    label="New F-Tool",
    description="Create a generic reference object and embedded feature",
    operator=ids.ADD_GENERIC_FTOOL_OT,
    icon="NODETREE",
    order=10,
)


def _reference_group(name):
    existing = bpy.data.node_groups.get(name)
    if existing is not None and existing.bl_idname == "GeometryNodeTree":
        return existing
    tree = bpy.data.node_groups.new(name, "GeometryNodeTree")
    tree.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    group_input = tree.nodes.new("NodeGroupInput")
    group_output = tree.nodes.new("NodeGroupOutput")
    group_input.location = (-180.0, 0.0)
    group_output.location = (180.0, 0.0)
    tree.links.new(group_input.outputs["Geometry"], group_output.inputs["Geometry"])
    return tree


def _embed_group(name):
    existing = bpy.data.node_groups.get(name)
    if existing is not None and existing.bl_idname == "GeometryNodeTree":
        return existing
    tree = bpy.data.node_groups.new(name, "GeometryNodeTree")
    tree.interface.new_socket(name="Object", in_out="INPUT", socket_type="NodeSocketObject")
    tree.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    group_input = tree.nodes.new("NodeGroupInput")
    object_info = tree.nodes.new("GeometryNodeObjectInfo")
    group_output = tree.nodes.new("NodeGroupOutput")
    group_input.location = (-300.0, 0.0)
    object_info.location = (-80.0, 0.0)
    group_output.location = (180.0, 0.0)
    tree.links.new(group_input.outputs["Object"], object_info.inputs["Object"])
    tree.links.new(object_info.outputs["Geometry"], group_output.inputs["Geometry"])
    return tree


def _create_reference(owner, instance_id, context):
    if owner is not None:
        corners = [Vector(corner) for corner in owner.bound_box]
        center = sum(corners, Vector()) / len(corners)
        collection = owner.users_collection[0] if owner.users_collection else context.scene.collection
    else:
        center = context.scene.cursor.location.copy()
        collection = getattr(context, "collection", None) or context.scene.collection
    mesh = bpy.data.meshes.new("F-Tool Reference")
    mesh.from_pydata([(0.0, 0.0, 0.0)], [], [])
    mesh.update()
    reference = bpy.data.objects.new("F-Tool Reference", mesh)
    collection.objects.link(reference)
    if owner is not None:
        reference.parent = owner
    reference.location = center
    reference.display_type = "WIRE"
    reference.show_in_front = True
    reference[TOOL_KEY] = "no3d.generic-ftool"
    reference[INSTANCE_KEY] = instance_id
    reference[ROLE_KEY] = "reference"
    modifier = reference.modifiers.new("F-Tool Reference", "NODES")
    modifier.node_group = _reference_group(ids.GENERIC_REFERENCE_GROUP)
    return reference, modifier


def instances_for_object(active_object):
    """Return discoverable generic instances related to the active object."""
    if active_object is None:
        return []
    if active_object.get(ROLE_KEY) == "reference":
        owners = [active_object.parent] if active_object.parent else []
        wanted = active_object.get(INSTANCE_KEY)
    else:
        owners = [active_object]
        wanted = None

    found = []
    for owner in owners:
        modifier = _active_geometry_nodes_modifier(owner)
        if modifier is None:
            continue
        for tree in _reachable_geometry_trees(modifier.node_group):
            for node in tree.nodes:
                instance_id = node.get(INSTANCE_KEY)
                if not instance_id or (wanted and instance_id != wanted):
                    continue
                object_input = _socket(node.inputs, "Object")
                reference = object_input.default_value if object_input is not None else None
                if reference is None:
                    reference = next(
                        (child for child in owner.children if child.get(INSTANCE_KEY) == instance_id),
                        None,
                    )
                reference_modifier = _active_geometry_nodes_modifier(reference) if reference else None
                found.append((instance_id, owner, reference, reference_modifier, node, object_input))
    return found


def _reachable_geometry_trees(root):
    pending = [root] if root is not None else []
    visited = set()
    while pending:
        tree = pending.pop()
        pointer = tree.as_pointer()
        if pointer in visited:
            continue
        visited.add(pointer)
        yield tree
        pending.extend(
            node.node_tree
            for node in tree.nodes
            if node.bl_idname == "GeometryNodeGroup" and node.node_tree is not None
        )


def _embed_node_by_instance(instance_id):
    for tree in bpy.data.node_groups:
        if tree.bl_idname != "GeometryNodeTree":
            continue
        for node in tree.nodes:
            node_instance_id = node.get(INSTANCE_KEY)
            if node_instance_id == instance_id:
                return node
    return None


def _instance_by_id(instance_id):
    reference = next(
        (
            obj for obj in bpy.data.objects
            if obj.get(INSTANCE_KEY) == instance_id and obj.get(ROLE_KEY) == "reference"
        ),
        None,
    )
    owner = reference.parent if reference else None
    if owner is None:
        return None
    embed_node = _embed_node_by_instance(instance_id)
    if embed_node is None:
        return None
    reference_modifier = _active_geometry_nodes_modifier(reference)
    return owner, reference, reference_modifier, embed_node


def _node_group_items(self, context):
    return [
        (group.name, group.name, "", "NODETREE", index)
        for index, group in enumerate(sorted(bpy.data.node_groups, key=lambda item: item.name.lower()))
        if group.bl_idname == "GeometryNodeTree"
    ]


class _NO3D_CAD_OT_set_feature_base:
    bl_property = "node_group"
    instance_id: StringProperty(options={"HIDDEN"})
    node_group: EnumProperty(name="Node Group", items=_node_group_items)

    def invoke(self, context, event):
        return invoke_search_popup(self, context)


class NO3D_CAD_OT_set_reference_feature(_NO3D_CAD_OT_set_feature_base, Operator):
    """Swap the Geometry Nodes feature on this F-Tool's reference object"""

    bl_idname = ids.SET_REFERENCE_FEATURE_OT
    bl_label = "Set Reference Feature"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        instance = _instance_by_id(self.instance_id)
        group = bpy.data.node_groups.get(self.node_group)
        if instance is None or group is None:
            self.report({"ERROR"}, "F-Tool instance or node group is no longer available")
            return {"CANCELLED"}
        reference_modifier = instance[2]
        if reference_modifier is None:
            self.report({"ERROR"}, "The reference object has no Geometry Nodes modifier")
            return {"CANCELLED"}
        reference_modifier.node_group = group
        return {"FINISHED"}


class NO3D_CAD_OT_set_embed_feature(_NO3D_CAD_OT_set_feature_base, Operator):
    """Swap the embedded feature and rebind this F-Tool's reference object"""

    bl_idname = ids.SET_EMBED_FEATURE_OT
    bl_label = "Set Embed Feature"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        instance = _instance_by_id(self.instance_id)
        group = bpy.data.node_groups.get(self.node_group)
        if instance is None or group is None:
            self.report({"ERROR"}, "F-Tool instance or node group is no longer available")
            return {"CANCELLED"}
        _owner, reference, _reference_modifier, embed_node = instance
        embed_node.node_tree = group
        object_input = _socket(embed_node.inputs, "Object")
        if object_input is None:
            self.report({"WARNING"}, f'"{group.name}" has no Object input to bind')
        else:
            object_input.default_value = reference
        return {"FINISHED"}


class NO3D_CAD_OT_add_generic_ftool(Operator):
    """Create a reference object and swappable embedded node-group feature"""

    bl_idname = ids.ADD_GENERIC_FTOOL_OT
    bl_label = "New F-Tool"
    bl_description = "Create a generic reference object and embedded feature with independently swappable node groups"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if edited_geometry_tree(context) is not None:
            return True
        owner = geometry_owner_from_context(context)
        return owner is not None and owner.mode == "OBJECT" and _active_geometry_nodes_modifier(owner) is not None

    def execute(self, context):
        owner = geometry_owner_from_context(context)
        edited_tree = edited_geometry_tree(context)
        owner_modifier = _active_geometry_nodes_modifier(owner)
        owner_tree = edited_tree if edited_tree is not None else owner_modifier.node_group
        output_node = None if edited_tree is not None else _active_geometry_output(owner_tree)
        output_geometry = _socket(output_node.inputs, "Geometry") if output_node else None
        if edited_tree is None and output_geometry is None:
            self.report({"ERROR"}, "The active Geometry Nodes tree has no Geometry output")
            return {"CANCELLED"}

        embed_definition = _embed_group(ids.GENERIC_EMBED_GROUP)
        upstream_link = output_geometry.links[0] if output_geometry and output_geometry.is_linked else None
        instance_id = str(uuid.uuid4())
        reference = None
        embed_node = None
        try:
            reference, _reference_modifier = _create_reference(owner, instance_id, context)
            embed_node = owner_tree.nodes.new("GeometryNodeGroup")
            embed_node.node_tree = embed_definition
            embed_node.label = "F-Tool"
            embed_node.location = (
                node_cursor_location(context)
                if edited_tree is not None
                else (output_node.location.x - 220.0, output_node.location.y)
            )
            embed_node[TOOL_KEY] = "no3d.generic-ftool"
            embed_node[INSTANCE_KEY] = instance_id
            embed_node[ROLE_KEY] = "embed"

            geometry_input = _socket(embed_node.inputs, "Geometry")
            geometry_output = _socket(embed_node.outputs, "Geometry")
            object_input = _socket(embed_node.inputs, "Object")
            if geometry_output is None or object_input is None:
                raise RuntimeError("The generic embed definition has an incompatible interface")

            if edited_tree is not None:
                pass
            elif geometry_input is not None and upstream_link is not None:
                upstream_socket = upstream_link.from_socket
                owner_tree.links.remove(upstream_link)
                owner_tree.links.new(upstream_socket, geometry_input)
            elif geometry_input is not None:
                group_input = next((node for node in owner_tree.nodes if node.bl_idname == "NodeGroupInput"), None)
                source_geometry = _socket(group_input.outputs, "Geometry") if group_input else None
                if source_geometry is None:
                    raise RuntimeError("No upstream Geometry socket is available")
                owner_tree.links.new(source_geometry, geometry_input)
            elif upstream_link is not None:
                owner_tree.links.remove(upstream_link)
            object_input.default_value = reference
            if edited_tree is None:
                owner_tree.links.new(geometry_output, output_geometry)
        except Exception as exc:
            if embed_node is not None:
                owner_tree.nodes.remove(embed_node)
            if reference is not None:
                mesh = reference.data
                bpy.data.objects.remove(reference, do_unlink=True)
                if mesh.users == 0:
                    bpy.data.meshes.remove(mesh)
            self.report({"ERROR"}, f"Could not create F-Tool: {exc}")
            return {"CANCELLED"}

        if context.area and context.area.type == "VIEW_3D":
            for other in context.selected_objects:
                other.select_set(False)
            reference.select_set(True)
            context.view_layer.objects.active = reference
        return {"FINISHED"}


def draw_instance_config(layout, context):
    instances = instances_for_object(object_from_context(context))
    if not instances:
        return
    layout.separator()
    layout.label(text="Active F-Tool", icon="MOD_NODES")
    for instance_id, _owner, reference, reference_modifier, embed_node, object_input in instances:
        box = layout.box()
        box.label(text=f"F-Tool {instance_id[:8]}")
        if reference is not None:
            box.prop(reference, "name", text="Reference")
        if reference_modifier is not None:
            operator = box.operator(
                ids.SET_REFERENCE_FEATURE_OT,
                text=f"Reference: {reference_modifier.node_group.name}",
                icon="NODETREE",
            )
            operator.instance_id = instance_id
        operator = box.operator(
            ids.SET_EMBED_FEATURE_OT,
            text=f"Embed: {embed_node.node_tree.name}",
            icon="NODETREE",
        )
        operator.instance_id = instance_id
        if object_input is not None:
            box.prop(object_input, "default_value", text="Object")
        else:
            box.label(text="Embed feature has no Object input", icon="ERROR")


CLASSES = (
    NO3D_CAD_OT_add_generic_ftool,
    NO3D_CAD_OT_set_reference_feature,
    NO3D_CAD_OT_set_embed_feature,
)
