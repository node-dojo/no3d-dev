"""Toolbox section — parent N-panel; each WIP feature is its own sub-section.

The Toolbox panel is the container. Every feature gets a collapsible sub-panel
(bl_parent_id = Toolbox) so the N-panel mirrors the prefs feature table: one
sub-section per feature. View Align's sub-panel lives here; WIP Tools' lives in
make_spin.py. Sub-panel idnames come from ids.FEATURES.
"""

import bpy

from . import ids


class NO3D_WIP_PT_toolbox(bpy.types.Panel):
    bl_idname = ids.TOOLBOX_PANEL_IDNAME
    bl_label = ids.TOOLBOX_PANEL_LABEL
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = ids.NPANEL_CATEGORY

    def draw(self, context):
        # Container only — features render in the sub-panels below.
        self.layout.label(text="WIP features", icon="DOT")


class NO3D_WIP_PT_feature_view_align(bpy.types.Panel):
    """View Align sub-section."""
    bl_idname = ids.VIEW_ALIGN_SUBPANEL_IDNAME
    bl_label = ids.VIEW_ALIGN_PIE_LABEL
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = ids.NPANEL_CATEGORY
    bl_parent_id = ids.TOOLBOX_PANEL_IDNAME
    bl_options = {"DEFAULT_CLOSED"}

    def draw_header(self, context):
        self.layout.label(text="", icon="MOD_MIRROR")

    def draw(self, context):
        layout = self.layout
        layout.label(text="Alt+A in viewport", icon="EVENT_A")
        row = layout.row(align=True)
        row.operator(ids.VIEW_ALIGN_OT_IDNAME, text="Left").direction = ids.DIR_LEFT
        row.operator(ids.VIEW_ALIGN_OT_IDNAME, text="Right").direction = ids.DIR_RIGHT
        row = layout.row(align=True)
        row.operator(ids.VIEW_ALIGN_OT_IDNAME, text="Top").direction = ids.DIR_TOP
        row.operator(ids.VIEW_ALIGN_OT_IDNAME, text="Bottom").direction = ids.DIR_BOTTOM
        layout.operator(ids.VIEW_ALIGN_OT_IDNAME, text="Center").direction = ids.DIR_CENTER


CLASSES = (
    NO3D_WIP_PT_toolbox,
    NO3D_WIP_PT_feature_view_align,
)
