"""Factory-startup acceptance test for Power Panel architecture and routing."""

import importlib
from pathlib import Path
import sys

import bpy


EXTENSIONS = Path(__file__).resolve().parents[1] / "extensions"
sys.path.insert(0, str(EXTENSIONS))
host = importlib.import_module("no3d_asset_developer")
power_panel = importlib.import_module("no3d_asset_developer.power_panel")
config = importlib.import_module("no3d_asset_developer.power_panel.config")
router = importlib.import_module("no3d_asset_developer.power_panel.router")
slots = importlib.import_module("no3d_asset_developer.power_panel.slots")
pie = importlib.import_module("no3d_asset_developer.power_panel.pie")


class TEST_PT_toolbox(bpy.types.Panel):
    bl_idname = "NO3D_WIP_PT_toolbox"
    bl_label = "Toolbox"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "NO3D Dev"
    bl_order = 77

    def draw(self, _context):
        pass


class TEST_PT_align(bpy.types.Panel):
    bl_idname = "NO3D_WIP_PT_feature_view_align"
    bl_label = "View Align"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "NO3D Dev"
    bl_parent_id = "NO3D_WIP_PT_toolbox"

    def draw(self, _context):
        pass


class TEST_PT_capture(bpy.types.Panel):
    bl_idname = "NO3D_PT_viewport_screenshot"
    bl_label = "Viewport Screenshot"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "NO3D Dev"

    def draw(self, _context):
        pass


class AGENT_BRIDGE_PT_panel(bpy.types.Panel):
    bl_idname = "AGENT_BRIDGE_PT_panel"
    bl_label = "Agent Bridge"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Claude"

    def draw(self, _context):
        pass


CLASSES = (TEST_PT_toolbox, TEST_PT_align, TEST_PT_capture, AGENT_BRIDGE_PT_panel)
for cls in CLASSES:
    bpy.utils.register_class(cls)

try:
    assert router.apply_routes()
    assert TEST_PT_toolbox.bl_category == "NO3D Create"
    assert TEST_PT_toolbox.bl_order == 10
    assert TEST_PT_align.bl_category == "NO3D Create"
    assert TEST_PT_align.bl_parent_id == "NO3D_WIP_PT_toolbox"
    assert TEST_PT_capture.bl_category == "NO3D Capture"
    assert AGENT_BRIDGE_PT_panel.bl_category == "Agent"

    assert slots.apply_numbering()
    assert TEST_PT_toolbox.bl_category == "[2] NO3D Create"
    assert TEST_PT_capture.bl_category == "[3] NO3D Capture"
    assert AGENT_BRIDGE_PT_panel.bl_category == "[5] Agent"

    assert slots.restore_numbering()
    assert router.restore_routes()
    assert TEST_PT_toolbox.bl_category == "NO3D Dev"
    assert TEST_PT_toolbox.bl_order == 77
    assert TEST_PT_capture.bl_category == "NO3D Dev"
    # Retired Claude is deliberately normalized rather than restored.
    assert AGENT_BRIDGE_PT_panel.bl_category == "Agent"

    annotations = host.NO3D_AddonPreferences.__annotations__
    for slot in range(1, 10):
        assert f"{config.SLOT_PROPERTY_PREFIX}{slot}" in annotations

    power_panel.register()
    try:
        addon_items = [
            item
            for keymap in bpy.context.window_manager.keyconfigs.addon.keymaps
            for item in keymap.keymap_items
            if item.idname.startswith("view3d.no3d_")
        ]
        assert any(item.idname == "view3d.no3d_type_sidebar_tab_filter" for item in addon_items)
        assert any(item.idname == "view3d.no3d_power_panel" for item in addon_items)
        assert not any(item.type in {
            "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE"
        } for item in addon_items)
        # Private registration helpers must also heal stale semantic bindings
        # left by a replaced module during live extension development.
        power_panel.keymaps.register()
        addon_items = [
            item
            for keymap in bpy.context.window_manager.keyconfigs.addon.keymaps
            for item in keymap.keymap_items
        ]
        assert sum(item.idname == "view3d.no3d_type_sidebar_tab_filter" for item in addon_items) == 1
        assert sum(item.idname == "view3d.no3d_power_panel" for item in addon_items) == 1
    finally:
        power_panel.unregister()
finally:
    slots.restore_numbering()
    router.restore_routes()
    for cls in reversed(CLASSES):
        if cls.is_registered:
            bpy.utils.unregister_class(cls)

print("POWER_PANEL_TEST_OK")
