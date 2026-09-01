from pathlib import Path

import bpy
from bpy.props import StringProperty


class SENDNODES_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    publish_directory: StringProperty(
        name="Publish Directory",
        description="Folder inside a local Git repository where node bundles are written",
        subtype="DIR_PATH",
    )
    public_base_url: StringProperty(
        name="Public Base URL",
        description="Public raw-file URL corresponding to the publish directory",
        subtype="NONE",
    )

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "publish_directory")
        layout.prop(self, "public_base_url")
        if self.publish_directory:
            path = Path(bpy.path.abspath(self.publish_directory)).expanduser()
            layout.label(text=f"Resolved directory: {path}")


def get_preferences(context):
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


classes = (SENDNODES_Preferences,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
