"""Canvas Editor — borderless spatial documents on Blender's native node canvas."""

from __future__ import annotations

import bpy
from bpy.types import AddonPreferences, Operator, Panel

from . import drawing
from .model import NODE_CLASSES, register_properties, unregister_properties
from .operators import OPERATOR_CLASSES
from .ui import UI_CLASSES, register_menus, unregister_menus


bl_info = {
    "name": "Canvas Editor",
    "author": "Joe Bowers",
    "version": (0, 1, 0),
    "blender": (5, 2, 0),
    "location": "Node Editor > Sidebar > Canvas",
    "description": "Borderless spatial documents on Blender's native node canvas",
    "category": "Node",
}


class NO3D_CANVAS_Preferences(AddonPreferences):
    bl_idname = __package__

    def draw(self, context):
        layout = self.layout
        layout.label(text="Canvas Editor is an experimental Blender-native canvas.")
        layout.operator("no3d_canvas.open", icon="WINDOW")


class NO3D_CANVAS_OT_open_from_view(Operator):
    bl_idname = "no3d_canvas.open_from_view"
    bl_label = "Open Canvas Editor"
    bl_description = "Open directly onto an untitled Canvas"

    def execute(self, context):
        return bpy.ops.no3d_canvas.open()


class NO3D_CANVAS_PT_launcher(Panel):
    bl_idname = "NO3D_CANVAS_PT_launcher"
    bl_label = "Canvas Editor"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "NO3D Dev"

    def draw(self, context):
        self.layout.operator("no3d_canvas.open", icon="WINDOW")


ROOT_CLASSES = (
    NO3D_CANVAS_Preferences,
    NO3D_CANVAS_OT_open_from_view,
    NO3D_CANVAS_PT_launcher,
)


def register():
    for cls in NODE_CLASSES:
        bpy.utils.register_class(cls)
    register_properties()
    for cls in OPERATOR_CLASSES:
        bpy.utils.register_class(cls)
    for cls in UI_CLASSES:
        bpy.utils.register_class(cls)
    for cls in ROOT_CLASSES:
        bpy.utils.register_class(cls)
    register_menus()
    drawing.install_draw_handler()


def unregister():
    drawing.remove_draw_handler()
    unregister_menus()
    for cls in reversed(ROOT_CLASSES):
        if cls.is_registered:
            bpy.utils.unregister_class(cls)
    for cls in reversed(UI_CLASSES):
        if cls.is_registered:
            bpy.utils.unregister_class(cls)
    for cls in reversed(OPERATOR_CLASSES):
        if cls.is_registered:
            bpy.utils.unregister_class(cls)
    unregister_properties()
    for cls in reversed(NODE_CLASSES):
        if cls.is_registered:
            bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
