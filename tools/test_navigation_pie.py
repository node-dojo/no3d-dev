"""Blender factory-startup smoke test for numbered N-panel pie navigation."""

import importlib
from pathlib import Path
import sys
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1] / "extensions"
sys.path.insert(0, str(ROOT))

importlib.import_module("no3d_asset_developer")
pie = importlib.import_module("no3d_asset_developer.power_panel.pie")
config = importlib.import_module("no3d_asset_developer.power_panel.config")

pie.register()
pie._register_keymap()
try:
    assert pie.NO3D_AD_OT_open_sidebar_slot.is_registered
    assert pie.VIEW3D_MT_no3d_sidebar_tabs_pie.is_registered
    assert pie._slot_categories() == {
        1: "NO3D Dev",
        2: "NO3D Create",
        3: "NO3D Capture",
        4: "No3D Tools",
        5: "Agent",
    }
    assert len(pie._addon_keymaps) == 1
    keymap, item = pie._addon_keymaps[0]
    assert keymap.name == "3D View"
    assert item.idname == "view3d.no3d_power_panel"
    assert item.type == "TAB"
    assert item.alt and not item.shift and not item.ctrl and not item.oskey
    assert config.PIE_DIRECTIONS == (
        ("WEST", "slot", 1, "NO3D Dev"),
        ("EAST", "slot", 4, "No3D Tools"),
        ("SOUTH", "slot", 3, "NO3D Capture"),
        ("NORTH", "slot", 2, "NO3D Create"),
        ("NORTHWEST", "slot", 5, "Agent Bridge"),
        ("NORTHEAST", "search", 0, "Search All Tabs"),
        ("SOUTHWEST", "toggle", 0, "Toggle Sidebar"),
        ("SOUTHEAST", "previous", 0, "Last Used Tab"),
    )
    assert pie._NUMBER_EVENTS["ONE"] == 1
    assert pie._NUMBER_EVENTS["NINE"] == 9
    selected = []
    dummy = SimpleNamespace(
        _select_slot=lambda _context, slot: selected.append(slot) or {"FINISHED"},
    )
    event = SimpleNamespace(
        value="PRESS", type="FIVE", ctrl=False, shift=False, alt=False, oskey=False
    )
    result = pie.NO3D_PP_OT_invoke_navigation.modal(dummy, None, event)
    assert result == {"FINISHED"}
    assert selected == [5]
finally:
    pie.unregister()

assert not pie._addon_keymaps
print("NAVIGATION_PIE_OK")
