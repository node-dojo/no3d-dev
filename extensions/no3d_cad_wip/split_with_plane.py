"""Add Split with Plane Feature Tool."""

from __future__ import annotations

import bpy
from mathutils import Vector
from bpy.types import Operator

from . import ids
from .contexts import active_geometry_nodes_modifier
from .contexts import edited_geometry_tree, node_cursor_location
from .feature_tools import FeatureToolSpec
from .library import LIB_BLEND, get_or_fetch_group


FEATURE_TOOL_SPEC = FeatureToolSpec(
    id="split_with_plane",
    label="Add Split with Plane",
    description="Create and bind a plane-driven split feature",
    operator=ids.ADD_SPLIT_PLANE_OT,
    icon="MOD_BOOLEAN",
    order=30,
)


def _active_geometry_nodes_modifier(obj):
    return active_geometry_nodes_modifier(obj)


def _socket(sockets, name):
    return next((socket for socket in sockets if socket.name == name), None)


def _active_geometry_output(tree):
    candidates = [node for node in tree.nodes if node.bl_idname == "NodeGroupOutput"]
    return next((node for node in candidates if getattr(node, "is_active_output", False)), None) or (
        candidates[0] if candidates else None
    )


def _create_plane(owner):
    corners = [Vector(corner) for corner in owner.bound_box]
    center = sum(corners, Vector()) / len(corners)
    extents = [max(corner[i] for corner in corners) - min(corner[i] for corner in corners) for i in range(3)]
    size = max(max(extents) * 1.25, 0.001)
    half = size * 0.5

    mesh = bpy.data.meshes.new("Split Plane")
    mesh.from_pydata(
        [(-half, -half, 0.0), (half, -half, 0.0), (-half, half, 0.0), (half, half, 0.0)],
        [],
        [(0, 1, 3, 2)],
    )
    mesh.update()
    plane = bpy.data.objects.new("Split Plane", mesh)
    owner.users_collection[0].objects.link(plane)
    plane.display_type = "WIRE"
    plane.show_in_front = True
    plane.parent = owner
    plane.location = center
    plane["no3d_feature_tool"] = "no3d.split-with-plane"
    plane["no3d_feature_owner"] = owner.name
    return plane


class NO3D_CAD_OT_add_split_with_plane(Operator):
    """Create a plane reference and insert Split with Plane in the active GN graph"""

    bl_idname = ids.ADD_SPLIT_PLANE_OT
    bl_label = "Add Split with Plane"
    bl_description = "Add a wire plane and bind a Split with Plane feature into the active object's Geometry Nodes"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        from .contexts import geometry_owner_from_context

        owner = geometry_owner_from_context(context)
        return owner is not None and owner.mode == "OBJECT" and _active_geometry_nodes_modifier(owner) is not None

    def execute(self, context):
        from .contexts import geometry_owner_from_context

        owner = geometry_owner_from_context(context)
        modifier = _active_geometry_nodes_modifier(owner)
        edited_tree = edited_geometry_tree(context)
        owner_tree = edited_tree or modifier.node_group
        definition = get_or_fetch_group(
            (ids.SPLIT_WITH_PLANE_GROUP, ids.SPLIT_WITH_PLANE_GROUP_FALLBACK),
            asset_library=ids.WIP_LIBRARY_NAME,
            asset_blend=ids.SPLIT_WITH_PLANE_ASSET_BLEND,
        )
        if definition is None:
            self.report({"ERROR"}, f'"{ids.SPLIT_WITH_PLANE_GROUP}" is not in this file or {LIB_BLEND}')
            return {"CANCELLED"}

        output_node = None if edited_tree is not None else _active_geometry_output(owner_tree)
        output_geometry = _socket(output_node.inputs, "Geometry") if output_node else None
        definition_inputs = [
            item for item in definition.interface.items_tree if getattr(item, "in_out", None) == "INPUT"
        ]
        definition_outputs = [
            item for item in definition.interface.items_tree if getattr(item, "in_out", None) == "OUTPUT"
        ]
        has_geometry_input = any(item.name == "Geometry" for item in definition_inputs)
        has_geometry_output = any(item.name == "Geometry" for item in definition_outputs)
        has_object_input = any(item.name == "Object" for item in definition_inputs)
        if (
            (edited_tree is None and output_geometry is None)
            or not (has_geometry_input and has_geometry_output and has_object_input)
        ):
            self.report({"ERROR"}, "The owner output or Split with Plane interface is incomplete")
            return {"CANCELLED"}

        upstream_link = output_geometry.links[0] if output_geometry and output_geometry.is_linked else None
        plane = None
        feature_node = None
        try:
            plane = _create_plane(owner)
            feature_node = owner_tree.nodes.new("GeometryNodeGroup")
            feature_node.node_tree = definition
            feature_node.location = (
                node_cursor_location(context)
                if edited_tree is not None
                else (output_node.location.x - 220.0, output_node.location.y)
            )

            geometry_input = _socket(feature_node.inputs, "Geometry")
            geometry_output = _socket(feature_node.outputs, "Geometry")
            object_input = _socket(feature_node.inputs, "Object")
            seam_input = _socket(feature_node.inputs, "Seam tolerance")
            if geometry_input is None or geometry_output is None or object_input is None:
                raise RuntimeError("Instantiated feature sockets do not match the definition")

            if edited_tree is not None:
                pass
            elif upstream_link is not None:
                upstream_socket = upstream_link.from_socket
                owner_tree.links.remove(upstream_link)
                owner_tree.links.new(upstream_socket, geometry_input)
            else:
                group_input = next((node for node in owner_tree.nodes if node.bl_idname == "NodeGroupInput"), None)
                input_geometry = _socket(group_input.outputs, "Geometry") if group_input else None
                if input_geometry is None:
                    raise RuntimeError("No upstream Geometry socket is available")
                owner_tree.links.new(input_geometry, geometry_input)

            object_input.default_value = plane
            if seam_input is not None:
                seam_input.default_value = 0.1
            if edited_tree is None:
                owner_tree.links.new(geometry_output, output_geometry)
        except Exception as exc:
            if feature_node is not None:
                owner_tree.nodes.remove(feature_node)
            if plane is not None:
                mesh = plane.data
                bpy.data.objects.remove(plane, do_unlink=True)
                if mesh.users == 0:
                    bpy.data.meshes.remove(mesh)
            self.report({"ERROR"}, f"Could not create Split with Plane: {exc}")
            return {"CANCELLED"}

        if context.area and context.area.type == "VIEW_3D":
            for other in context.selected_objects:
                other.select_set(False)
            plane.select_set(True)
            context.view_layer.objects.active = plane
            region = next((item for item in context.area.regions if item.type == "WINDOW"), None)
            if region is not None:
                try:
                    with context.temp_override(area=context.area, region=region):
                        bpy.ops.transform.translate("INVOKE_DEFAULT")
                except RuntimeError as exc:
                    self.report({"WARNING"}, f"Feature created, but placement did not start: {exc}")
        return {"FINISHED"}


CLASSES = (NO3D_CAD_OT_add_split_with_plane,)
