"""No3d CAD.wip — live Feature Tool development container."""

from __future__ import annotations

import importlib
import sys

import bpy
from bpy.types import AddonPreferences, Operator, Panel

from . import contexts, feature_tools, generic_ftool, ids, make_spin, mesh_line, object_references, split_with_plane


bl_info = {
    "name": "No3d CAD.wip",
    "author": "Joe Bowers",
    "version": (0, 6, 0),
    "blender": (5, 2, 0),
    "location": "View3D > Sidebar > NO3D Dev",
    "description": "Live development container for native No3d CAD workflows",
    "category": "3D View",
}


class NO3D_CAD_Preferences(AddonPreferences):
    bl_idname = __package__

    def draw(self, context):
        layout = self.layout
        layout.label(text="No3d CAD.wip — native Feature Tool development.")
        layout.label(text="Saved modeling results must remain native to Blender.")
        layout.label(text="Feature Tools: Generic, Make Spin, Split with Plane", icon="NODETREE")


def _reload_package(package_name: str):
    """Reload this small package after the invoking operator has returned."""
    module = sys.modules.get(package_name)
    if module is None:
        return None

    try:
        module.unregister()
        for child_name in (
            "ids", "library", "contexts", "feature_tools", "make_spin", "split_with_plane",
            "generic_ftool", "mesh_line", "object_references",
        ):
            child = sys.modules.get(f"{package_name}.{child_name}")
            if child is not None:
                importlib.reload(child)
        module = importlib.reload(module)
        module.register()
        print("NO3D_CAD_WIP_RELOAD_OK")
    except Exception as exc:
        print(f"NO3D_CAD_WIP_RELOAD_ERROR: {exc!r}")
    return None


class NO3D_CAD_OT_reload_wip(Operator):
    bl_idname = ids.RELOAD_OT
    bl_label = "Reload No3d CAD.wip"
    bl_description = "Reload No3d CAD.wip directly from its development source"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        package_name = __package__
        bpy.app.timers.register(
            lambda: _reload_package(package_name),
            first_interval=0.1,
        )
        self.report({"INFO"}, "No3d CAD.wip reload queued")
        return {"FINISHED"}


def _draw_feature_tools(layout):
    feature_tools.draw_feature_tools(layout)
    layout.row().operator(ids.PUBLISH_MAKE_SPIN_OT, icon="EXPORT")


class NO3D_CAD_PT_wip(Panel):
    bl_idname = ids.VIEW3D_PANEL
    bl_label = "No3d CAD.wip"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = ids.NPANEL_CATEGORY

    def draw(self, context):
        layout = self.layout
        status = layout.box()
        status.label(text="Feature Tool development", icon="NODETREE")
        _draw_feature_tools(layout)
        generic_ftool.draw_instance_config(layout, context)
        layout.separator()
        layout.operator(NO3D_CAD_OT_reload_wip.bl_idname, icon="FILE_REFRESH")


class NO3D_CAD_PT_node_tools(Panel):
    bl_idname = ids.NODE_PANEL
    bl_label = "No3d CAD.wip"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = ids.NPANEL_CATEGORY

    @classmethod
    def poll(cls, context):
        return getattr(context.space_data, "tree_type", None) == "GeometryNodeTree"

    def draw(self, context):
        _draw_feature_tools(self.layout)
        generic_ftool.draw_instance_config(self.layout, context)


CLASSES = (
    NO3D_CAD_Preferences,
    NO3D_CAD_OT_reload_wip,
    NO3D_CAD_PT_wip,
    NO3D_CAD_PT_node_tools,
)

SECTIONS = (make_spin, split_with_plane, generic_ftool, mesh_line, object_references, feature_tools)
FEATURE_TOOL_SPECS = (
    generic_ftool.FEATURE_TOOL_SPEC,
    make_spin.FEATURE_TOOL_SPEC,
    split_with_plane.FEATURE_TOOL_SPEC,
)

_addon_keymaps = []


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    for section in SECTIONS:
        for cls in section.CLASSES:
            bpy.utils.register_class(cls)
    for spec in FEATURE_TOOL_SPECS:
        feature_tools.register_feature_tool(spec)
    bpy.types.UI_MT_button_context_menu.append(object_references.draw_button_context)
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig is not None:
        keymap = keyconfig.keymaps.new(name="Node Editor", space_type="NODE_EDITOR")
        item = keymap.keymap_items.new(ids.FEATURE_TOOL_SEARCH_OT, "F", "PRESS", shift=True)
        _addon_keymaps.append((keymap, item))
        view_keymap = keyconfig.keymaps.new(name="3D View", space_type="VIEW_3D")
        line_item = view_keymap.keymap_items.new(ids.ADD_MESH_LINE_OT, "FOUR", "PRESS", shift=True)
        feature_line_item = view_keymap.keymap_items.new(
            ids.ADD_MESH_LINE_FEATURE_OT, "FOUR", "PRESS", shift=True, oskey=True,
        )
        _addon_keymaps.extend(((view_keymap, line_item), (view_keymap, feature_line_item)))


def unregister():
    for keymap, item in reversed(_addon_keymaps):
        keymap.keymap_items.remove(item)
    _addon_keymaps.clear()
    try:
        bpy.types.UI_MT_button_context_menu.remove(object_references.draw_button_context)
    except ValueError:
        pass
    for spec in reversed(FEATURE_TOOL_SPECS):
        feature_tools.unregister_feature_tool(spec.id)
    for section in reversed(SECTIONS):
        for cls in reversed(section.CLASSES):
            if cls.is_registered:
                bpy.utils.unregister_class(cls)
    for cls in reversed(CLASSES):
        if cls.is_registered:
            bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
