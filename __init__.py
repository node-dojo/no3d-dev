bl_info = {
    "name": "No3d Asset Developer",
    "author": "NO3D Tools",
    "version": (3, 0, 0),
    "blender": (5, 0, 0),
    "location": "Asset Browser > Context Menu | 3D Viewport > N-Panel > No3D Dev",
    "description": "Export marked assets as clean, individual .blend files with frontmatter, thumbnails, and dev notes. WIP folder auto-sync.",
    "category": "Asset",
    "doc_url": "",
    "tracker_url": "",
}

import datetime
import os

import bpy
from bpy.types import AddonPreferences
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from . import operators
from . import ui
from . import wip_sync
from .notes import note_manager


# NOTE: Method A (TEMPLATE_APPEND) is retained in code but no longer exposed in
# the UI — Method B (DATABLOCK_WRITE) is the sole user-facing pipeline. This enum
# is kept so the dispatcher and the console escape hatch still resolve both
# identifiers; the picker was removed from ui.py (see _draw_extract_v3).
EXTRACTION_METHOD_ITEMS = [
    (
        "TEMPLATE_APPEND",
        "Method A — Template Append",
        "Subprocess: opens _export_template.blend, appends the asset, strips smuggled markings, "
        "purges orphans, saves. Preserves scene and METRIC/mm units. Default for production.",
    ),
    (
        "DATABLOCK_WRITE",
        "Method B — Datablock Write",
        "In-process: bpy.data.libraries.write({asset}). Pose-library-native. No subprocess, no "
        "template. Faster. Output has no Scene/units; transitive deps come along.",
    ),
]


class NO3D_AddonPreferences(AddonPreferences):
    """Add-on preferences for No3d Asset Developer"""
    bl_idname = __name__

    default_vendor: StringProperty(
        name="Default Vendor",
        description="Default vendor name for exported assets",
        default="The Well Tarot",
    )

    default_product_type: StringProperty(
        name="Default Product Type",
        description="Default product type for exported assets",
        default="Blender Add-on",
    )

    export_library_path: StringProperty(
        name="Export Library Path",
        description="Default export directory for assets",
        subtype='DIR_PATH',
        default="",
    )

    def draw(self, context):
        layout = self.layout

        # Version Information
        box = layout.box()
        box.label(text="Version Information", icon='INFO')
        row = box.row()
        row.label(text=f"Version: {'.'.join(map(str, bl_info['version']))}")
        try:
            mtime = os.path.getmtime(__file__)
            stamp = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            box.row().label(text=f"Last updated: {stamp}")
        except OSError:
            pass

        layout.separator()

        # Export Defaults
        box = layout.box()
        box.label(text="Export Defaults", icon='EXPORT')
        box.prop(self, "default_vendor")
        box.prop(self, "default_product_type")
        box.prop(self, "export_library_path")

        layout.separator()

        # Update Section
        box = layout.box()
        box.label(text="Update Add-on", icon='FILE_REFRESH')
        box.operator(
            "preferences.addon_update_no3d",
            text="Update Add-on",
            icon='IMPORT'
        )
        box.label(text="Select the latest .zip file to install", icon='INFO')


def _on_wip_folder_changed(self, context):
    """When the user picks a WIP folder in the N-panel, persist it to prefs."""
    addon = context.preferences.addons.get(__name__)
    if addon and hasattr(addon, "preferences"):
        addon.preferences.export_library_path = self.no3d_wip_folder


def _default_wip_folder():
    """Seed the WM prop from addon preferences on register."""
    addon = bpy.context.preferences.addons.get(__name__)
    if addon and hasattr(addon, "preferences"):
        return addon.preferences.export_library_path or ""
    return ""


def _register_wm_props():
    bpy.types.WindowManager.no3d_extraction_method = EnumProperty(
        name="Extraction Method",
        description="Which pipeline to use when writing per-asset .blend files",
        items=EXTRACTION_METHOD_ITEMS,
        default="DATABLOCK_WRITE",
    )
    bpy.types.WindowManager.no3d_wip_folder = StringProperty(
        name="WIP Folder",
        description=(
            "Working folder where assets are auto-extracted on Mark / Save / Rename. "
            "Each asset gets its own subfolder. Saved back to addon preferences."
        ),
        subtype="DIR_PATH",
        default=_default_wip_folder(),
        update=_on_wip_folder_changed,
    )
    bpy.types.WindowManager.no3d_wip_auto_mark = BoolProperty(
        name="Auto-sync on Mark",
        description="Auto-extract a new asset to the WIP folder the moment it is marked",
        default=True,
    )
    bpy.types.WindowManager.no3d_wip_auto_save = BoolProperty(
        name="Auto-sync on Save",
        description="On every file save, re-extract assets whose source has changed",
        default=True,
    )
    bpy.types.WindowManager.no3d_wip_auto_rename = BoolProperty(
        name="Auto-sync on Rename",
        description="When an asset is renamed, rename its WIP folder to match",
        default=True,
    )
    bpy.types.WindowManager.no3d_wip_recent_count = IntProperty(
        name="Recents Shown",
        description="How many of the most recently saved assets to list",
        default=8,
        min=1,
        max=30,
    )


def _unregister_wm_props():
    for prop in (
        "no3d_extraction_method",
        "no3d_wip_folder",
        "no3d_wip_auto_mark",
        "no3d_wip_auto_save",
        "no3d_wip_auto_rename",
        "no3d_wip_recent_count",
    ):
        try:
            delattr(bpy.types.WindowManager, prop)
        except AttributeError:
            pass


def register():
    bpy.utils.register_class(NO3D_AddonPreferences)
    _register_wm_props()
    note_manager.register()
    operators.register()
    ui.register()
    wip_sync.register()


def unregister():
    wip_sync.unregister()
    ui.unregister()
    operators.unregister()
    note_manager.unregister()
    _unregister_wm_props()
    bpy.utils.unregister_class(NO3D_AddonPreferences)


if __name__ == "__main__":
    register()
