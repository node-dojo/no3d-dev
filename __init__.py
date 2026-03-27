bl_info = {
    "name": "No3d Asset Developer",
    "author": "NO3D Tools",
    "version": (2, 0, 0),
    "blender": (5, 0, 0),
    "location": "Asset Browser > Context Menu",
    "description": "Export assets with frontmatter metadata, thumbnails, and dev notes",
    "category": "Asset",
    "doc_url": "",
    "tracker_url": "",
}

import bpy
from bpy.types import AddonPreferences
from bpy.props import StringProperty
from . import operators
from . import ui
from .notes import note_manager


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


def register():
    bpy.utils.register_class(NO3D_AddonPreferences)
    note_manager.register()
    operators.register()
    ui.register()


def unregister():
    ui.unregister()
    operators.unregister()
    note_manager.unregister()
    bpy.utils.unregister_class(NO3D_AddonPreferences)


if __name__ == "__main__":
    register()
