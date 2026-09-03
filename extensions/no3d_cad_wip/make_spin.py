"""Make Spin Feature Tool, moved from the Asset Developer WIP toolbox."""

from __future__ import annotations

import bpy
from bpy.types import Operator

from . import ids
from .feature_tools import FeatureToolSpec
from .library import LIB_BLEND, get_or_fetch_group, publish_group


FEATURE_TOOL_SPEC = FeatureToolSpec(
    id="make_spin",
    label="Make Spin",
    description="Create a point-driven Make Spin feature object",
    operator=ids.MAKE_SPIN_OT,
    icon="EMPTY_SINGLE_ARROW",
    order=20,
)


class NO3D_CAD_OT_make_spin(Operator):
    """Create a one-point feature object using the make spin definition"""

    bl_idname = ids.MAKE_SPIN_OT
    bl_label = "Make Spin"
    bl_description = "Create a one-point Make Spin feature and begin placing its point"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"

    def execute(self, context):
        node_group = get_or_fetch_group(
            ids.MAKE_SPIN_GROUP,
            asset_library=ids.WIP_LIBRARY_NAME,
            asset_blend=ids.MAKE_SPIN_ASSET_BLEND,
        )
        if node_group is None:
            self.report({"ERROR"}, f'"{ids.MAKE_SPIN_GROUP}" is not in this file or {LIB_BLEND}')
            return {"CANCELLED"}

        mesh = bpy.data.meshes.new("Make Spin")
        mesh.from_pydata([(0.0, 0.0, 0.0)], [], [])
        mesh.update()
        feature = bpy.data.objects.new("Make Spin", mesh)
        feature.location = context.scene.cursor.location.copy()
        context.collection.objects.link(feature)
        feature["no3d_feature_tool"] = "no3d.make-spin"

        for other in context.selected_objects:
            other.select_set(False)
        feature.select_set(True)
        context.view_layer.objects.active = feature
        modifier = feature.modifiers.new(name=ids.MAKE_SPIN_GROUP, type="NODES")
        modifier.node_group = node_group

        bpy.ops.object.mode_set(mode="EDIT")
        context.tool_settings.mesh_select_mode = (True, False, False)
        bpy.ops.mesh.select_all(action="SELECT")
        region = None
        if context.area and context.area.type == "VIEW_3D":
            region = next((item for item in context.area.regions if item.type == "WINDOW"), None)
        if region is not None:
            try:
                with context.temp_override(area=context.area, region=region):
                    bpy.ops.transform.translate("INVOKE_DEFAULT")
            except RuntimeError as exc:
                self.report({"WARNING"}, f"Feature created, but placement did not start: {exc}")
        return {"FINISHED"}


class NO3D_CAD_OT_publish_make_spin(Operator):
    """Publish this file's make spin definition to the CAD WIP library"""

    bl_idname = ids.PUBLISH_MAKE_SPIN_OT
    bl_label = "Publish Make Spin"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        group = bpy.data.node_groups.get(ids.MAKE_SPIN_GROUP)
        return group is not None and group.bl_idname == "GeometryNodeTree"

    def execute(self, context):
        try:
            publish_group(bpy.data.node_groups[ids.MAKE_SPIN_GROUP])
        except OSError as exc:
            self.report({"ERROR"}, f"Could not write WIP library: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f'Published "{ids.MAKE_SPIN_GROUP}" to {LIB_BLEND}')
        return {"FINISHED"}


CLASSES = (NO3D_CAD_OT_make_spin, NO3D_CAD_OT_publish_make_spin)
