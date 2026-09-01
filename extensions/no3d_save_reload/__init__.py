# SPDX-License-Identifier: GPL-3.0-or-later
"""Independent No3d Save & Reload Blender extension."""

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty
from bpy.types import AddonPreferences

from . import save_op

bl_info = {
    "name": "No3d Save & Reload",
    "author": "Joe Bowers",
    "version": (1, 0, 0),
    "blender": (5, 0, 0),
    "category": "System",
}


class NO3D_SR_AddonPreferences(AddonPreferences):
    bl_idname = __package__

    save_folder: StringProperty(
        name="Save folder",
        description="Leave blank to save beside the current Blender file",
        default="",
        subtype="DIR_PATH",
    )
    iteration_digits: IntProperty(
        name="Iteration digits",
        description="Zero-padding width for iteration suffixes",
        default=3,
        min=2,
        max=6,
    )
    confirm_before_restart: BoolProperty(
        name="Confirm before restart",
        description="Confirm before saving, closing, and reopening Blender",
        default=False,
    )

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "save_folder")
        layout.prop(self, "iteration_digits")
        layout.prop(self, "confirm_before_restart")
        layout.label(text="Shortcut: Cmd+Shift+R in the 3D View. macOS only.", icon="INFO")


def register():
    bpy.utils.register_class(NO3D_SR_AddonPreferences)
    save_op.register()


def unregister():
    save_op.unregister()
    bpy.utils.unregister_class(NO3D_SR_AddonPreferences)
