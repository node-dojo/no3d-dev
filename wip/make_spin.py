"""WIP Tools — Make Spin WIP (moved here from No3d Asset Manager).

Drops a single-vert mesh object at the 3D cursor, attaches the "make spin"
Geometry Nodes modifier, and hands the vert to the user in a grab (G) so it
can be placed relative to the object's origin (which stays at the cursor).

The node group is fetched by name: from the current file if present,
otherwise appended from this add-on's bundled library blend. "Publish" writes
the group from the current file back into that library, so the group stays a
living, tweakable asset rather than a frozen copy.
"""

import os

import bpy
from bpy.types import Operator, Panel

from . import ids

# Self-contained: the library blend lives in this add-on's assets/ folder.
LIB_BLEND = os.path.join(os.path.dirname(__file__), "assets", "no3d_nodes.blend")


def get_or_fetch_group(name):
    """Return the named GeometryNodeTree: local first, else append from the
    bundled library blend. Returns None if unavailable in either place."""
    ng = bpy.data.node_groups.get(name)
    if ng is not None and ng.bl_idname == "GeometryNodeTree":
        return ng
    if not os.path.exists(LIB_BLEND):
        return None
    with bpy.data.libraries.load(LIB_BLEND, link=False) as (src, dst):
        if name not in src.node_groups:
            return None
        dst.node_groups = [name]
    ng = bpy.data.node_groups.get(name)
    if ng is not None and ng.bl_idname == "GeometryNodeTree":
        return ng
    return None


def publish_group(ng):
    """Write the node group (with its dependencies) into the library blend.
    The library currently holds only this group — libraries.write replaces
    the whole file, so widen this to a set if more groups join later."""
    ng.use_fake_user = True
    if not ng.asset_data:
        ng.asset_mark()
    os.makedirs(os.path.dirname(LIB_BLEND), exist_ok=True)
    bpy.data.libraries.write(LIB_BLEND, {ng}, fake_user=True, compress=True)


class NO3D_WIP_OT_make_spin(Operator):
    """Add a single vert at the 3D cursor with the make spin GN modifier, vert in-hand (G)"""
    bl_idname = ids.MAKE_SPIN_OT_IDNAME
    bl_label = ids.MAKE_SPIN_OT_LABEL
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"

    def execute(self, context):
        node_group = get_or_fetch_group(ids.MAKE_SPIN_GROUP)
        if node_group is None:
            self.report(
                {"ERROR"},
                f'"{ids.MAKE_SPIN_GROUP}" not in this file or the No3D library '
                f"({LIB_BLEND}) — publish it from a file that has it",
            )
            return {"CANCELLED"}

        # Single vert at local origin; object origin lands on the 3D cursor.
        mesh = bpy.data.meshes.new(ids.MAKE_SPIN_OT_LABEL)
        mesh.from_pydata([(0.0, 0.0, 0.0)], [], [])
        mesh.update()

        obj = bpy.data.objects.new(ids.MAKE_SPIN_OT_LABEL, mesh)
        obj.location = context.scene.cursor.location.copy()
        context.collection.objects.link(obj)

        for other in context.selected_objects:
            other.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj

        mod = obj.modifiers.new(name=ids.MAKE_SPIN_GROUP, type="NODES")
        mod.node_group = node_group

        bpy.ops.object.mode_set(mode="EDIT")
        context.tool_settings.mesh_select_mode = (True, False, False)
        bpy.ops.mesh.select_all(action="SELECT")

        # Hand the vert to the user (G). Needs the viewport WINDOW region —
        # the button click arrives from the sidebar's UI region. Non-fatal:
        # when run without a live viewport the vert just stays at the origin.
        region = next(
            (r for r in context.area.regions if r.type == "WINDOW"),
            None,
        ) if context.area and context.area.type == "VIEW_3D" else None
        if region is not None:
            try:
                with context.temp_override(area=context.area, region=region):
                    bpy.ops.transform.translate("INVOKE_DEFAULT")
            except RuntimeError as exc:
                self.report({"WARNING"}, f"Vert placed, but grab failed: {exc}")

        return {"FINISHED"}


class NO3D_WIP_OT_publish_make_spin(Operator):
    """Save this file's "make spin" node group into the No3D node library, so Make Spin WIP works in any project"""
    bl_idname = ids.PUBLISH_MAKE_SPIN_OT_IDNAME
    bl_label = ids.PUBLISH_MAKE_SPIN_OT_LABEL
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        ng = bpy.data.node_groups.get(ids.MAKE_SPIN_GROUP)
        return ng is not None and ng.bl_idname == "GeometryNodeTree"

    def execute(self, context):
        ng = bpy.data.node_groups.get(ids.MAKE_SPIN_GROUP)
        try:
            publish_group(ng)
        except OSError as exc:
            self.report({"ERROR"}, f"Could not write library: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f'Published "{ids.MAKE_SPIN_GROUP}" -> {LIB_BLEND}')
        return {"FINISHED"}


class NO3D_WIP_PT_wip_tools(Panel):
    """WIP modeling helpers — sub-section of the NO3D WIP Toolbox."""
    bl_idname = ids.WIP_TOOLS_SUBPANEL_IDNAME
    bl_label = ids.WIP_TOOLS_PANEL_LABEL
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = ids.NPANEL_CATEGORY
    bl_parent_id = ids.TOOLBOX_PANEL_IDNAME
    bl_options = {"DEFAULT_CLOSED"}

    def draw_header(self, context):
        self.layout.label(text="", icon="TOOL_SETTINGS")

    def draw(self, context):
        col = self.layout.column(align=True)
        col.scale_y = 1.3
        col.operator(ids.MAKE_SPIN_OT_IDNAME, text="Make Spin WIP", icon="EMPTY_SINGLE_ARROW")
        row = self.layout.row()
        row.operator(ids.PUBLISH_MAKE_SPIN_OT_IDNAME, text="Publish make spin", icon="EXPORT")


CLASSES = (
    NO3D_WIP_OT_make_spin,
    NO3D_WIP_OT_publish_make_spin,
    NO3D_WIP_PT_wip_tools,
)
