"""Persistent NO3D viewport navigation shortcuts."""

import bpy


_addon_keymaps = []


def register():
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig is None:
        return

    # Object Mode keeps plain F available for framing without replacing
    # Mesh Edit Mode's fundamental F = Make Face command.
    keymap = keyconfig.keymaps.new(name="Object Mode", space_type="VIEW_3D")
    item = keymap.keymap_items.new(
        "view3d.view_selected",
        "F",
        "PRESS",
    )
    item.properties.use_all_regions = False
    _addon_keymaps.append((keymap, item))


def unregister():
    for keymap, item in _addon_keymaps:
        try:
            keymap.keymap_items.remove(item)
        except (ReferenceError, RuntimeError):
            pass
    _addon_keymaps.clear()

