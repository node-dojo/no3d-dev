"""No3d CAD.wip — live development container.

The extension deliberately contains no modeling features yet. It establishes
the registration, UI, and reload boundaries into which verified No3d CAD
interactions can be added incrementally.
"""

from __future__ import annotations

import importlib
import sys

import bpy
from bpy.types import AddonPreferences, Operator, Panel


bl_info = {
    "name": "No3d CAD.wip",
    "author": "Joe Bowers",
    "version": (0, 1, 0),
    "blender": (5, 2, 0),
    "location": "View3D > Sidebar > NO3D Dev",
    "description": "Live development container for native No3d CAD workflows",
    "category": "3D View",
}


class NO3D_CAD_Preferences(AddonPreferences):
    bl_idname = __package__

    def draw(self, context):
        layout = self.layout
        layout.label(text="No3d CAD.wip is an experimental development container.")
        layout.label(text="Saved modeling results must remain native to Blender.")


def _reload_package(package_name: str):
    """Reload this small package after the invoking operator has returned."""
    module = sys.modules.get(package_name)
    if module is None:
        return None

    try:
        module.unregister()
        module = importlib.reload(module)
        module.register()
        print("NO3D_CAD_WIP_RELOAD_OK")
    except Exception as exc:
        print(f"NO3D_CAD_WIP_RELOAD_ERROR: {exc!r}")
    return None


class NO3D_CAD_OT_reload_wip(Operator):
    bl_idname = "no3d_cad.reload_wip"
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


class NO3D_CAD_PT_wip(Panel):
    bl_idname = "NO3D_CAD_PT_wip"
    bl_label = "No3d CAD.wip"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "NO3D Dev"

    def draw(self, context):
        layout = self.layout
        status = layout.box()
        status.label(text="Development container ready", icon="CHECKMARK")
        status.label(text="First feature: Custom Attributes")
        layout.operator(NO3D_CAD_OT_reload_wip.bl_idname, icon="FILE_REFRESH")


CLASSES = (
    NO3D_CAD_Preferences,
    NO3D_CAD_OT_reload_wip,
    NO3D_CAD_PT_wip,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        if cls.is_registered:
            bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()

