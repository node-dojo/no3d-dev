"""Blender factory-startup probe for native Mesh Plane NO3D defaults."""

import importlib.util
from pathlib import Path

import bpy


module_path = (
    Path(__file__).resolve().parents[1]
    / "extensions"
    / "no3d_asset_developer"
    / "clipboard_paste.py"
)
spec = importlib.util.spec_from_file_location("no3d_clipboard_paste_test", module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

module.register()
try:
    expected = module.MESH_PLANE_SHADER_DEFAULTS
    native = bpy.context.window_manager.operator_properties_last(
        "image.import_as_mesh_planes"
    )
    assert native is not None
    for name, value in expected.items():
        assert getattr(native, name) == value, (name, getattr(native, name), value)

    shortcuts = [
        item
        for _keymap, item in module._addon_keymaps
        if item.idname == "image.import_as_mesh_planes"
    ]
    assert len(shortcuts) == 1
    shortcut = shortcuts[0]
    assert shortcut.type == "FIVE" and shortcut.shift
    assert not shortcut.ctrl and not shortcut.alt and not shortcut.oskey
    for name, value in expected.items():
        assert getattr(shortcut.properties, name) == value

    assert module.NO3D_OT_drop_images_as_planes.is_registered
    assert module.NO3D_FH_drop_images_as_planes.is_registered
    assert not module._native_drop_handler_class.is_registered
finally:
    module.unregister()

assert not module.NO3D_FH_drop_images_as_planes.is_registered
assert module._native_drop_handler_class is None
from bl_operators.view3d import VIEW3D_FH_empty_image
assert VIEW3D_FH_empty_image.is_registered

print("MESH_PLANE_DEFAULTS_OK")
