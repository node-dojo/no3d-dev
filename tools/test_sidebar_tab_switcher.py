"""Blender factory-startup smoke test for searchable sidebar navigation."""

import importlib
from pathlib import Path
import sys

import bpy


extensions = Path(__file__).resolve().parents[1] / "extensions"
sys.path.insert(0, str(extensions))
importlib.import_module("no3d_asset_developer")
module = importlib.import_module("no3d_asset_developer.power_panel.search")

module.register()
module._register_keymap()
try:
    assert module.NO3D_AD_OT_search_sidebar_tabs.is_registered
    assert hasattr(bpy.ops.view3d, "no3d_search_sidebar_tabs")
    assert bpy.ops.view3d.no3d_search_sidebar_tabs.get_rna_type().properties.get("category") is not None

    items = module._category_items(None, bpy.context)
    identifiers = {item[0] for item in items}
    assert {"Item", "Tool", "View"}.issubset(identifiers)

    assert len(module._addon_keymaps) == 1
    keymap, item = module._addon_keymaps[0]
    assert keymap.name == "3D View"
    assert item.idname == "view3d.no3d_type_sidebar_tab_filter"
    assert item.type == "F5"
    assert not any((item.shift, item.ctrl, item.alt, item.oskey))
finally:
    module.unregister()

assert not module._addon_keymaps

print("SIDEBAR_TAB_SWITCHER_OK")
