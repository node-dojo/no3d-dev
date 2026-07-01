"""WIP section — folded in from the standalone "No3d Wip" add-on.

This is NOT a standalone add-on: it has no bl_info and does not run its own
register loop. The top-level No3d Asset Developer __init__ calls this package's
register()/unregister() helpers, which iterate the WIP feature sections exactly
as the source add-on did (register each section's CLASSES, then call any
register_keymap()), so the View Align Alt+A pie keymap still works.

The source add-on's AddonPreferences (NO3D_WIP_Preferences) is intentionally
dropped: a Blender add-on may have only one AddonPreferences, and it only
surfaced ids.FEATURES as a read-only table already mirrored by the Toolbox
sub-panels. No fields from it are read at runtime by align/make_spin.
"""

import bpy

from . import align, ids, make_spin, toolbox

# Order matches the source add-on (minus preferences). toolbox first so the
# container panel exists before the sub-panels that set bl_parent_id to it.
SECTIONS = (
    toolbox,
    align,
    make_spin,
)


def register():
    for section in SECTIONS:
        for cls in section.CLASSES:
            bpy.utils.register_class(cls)
        if hasattr(section, "register_keymap"):
            section.register_keymap()


def unregister():
    for section in reversed(SECTIONS):
        if hasattr(section, "unregister_keymap"):
            section.unregister_keymap()
        for cls in reversed(section.CLASSES):
            bpy.utils.unregister_class(cls)
