"""Blender factory-startup test for numbered and live-filtered N-panel tabs."""

import importlib
from pathlib import Path
import sys
from types import SimpleNamespace

import bpy


EXTENSIONS = Path(__file__).resolve().parents[1] / "extensions"
sys.path.insert(0, str(EXTENSIONS))
importlib.import_module("no3d_asset_developer")
numbered = importlib.import_module("no3d_asset_developer.power_panel.slots")
tab_filter = importlib.import_module("no3d_asset_developer.power_panel.filter")


class TEST_PT_no3d_dev(bpy.types.Panel):
    bl_idname = "TEST_PT_no3d_dev"
    bl_label = "NO3D Test"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "NO3D Dev"

    def draw(self, _context):
        pass


class TEST_PT_other(bpy.types.Panel):
    bl_idname = "TEST_PT_other"
    bl_label = "Other Test"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Other Test"

    def draw(self, _context):
        pass


class AGENT_BRIDGE_PT_panel(bpy.types.Panel):
    bl_idname = "AGENT_BRIDGE_PT_panel"
    bl_label = "Agent Bridge"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    # Simulate a long-running class left merged by No3d Dev 4.4.1.
    bl_category = "[1] NO3D Dev"

    def draw(self, _context):
        pass


class TEST_PT_eyecones_internal_no3d_name(bpy.types.Panel):
    bl_idname = "TEST_PT_eyecones_internal_no3d_name"
    bl_label = "Spotify"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Eyecones"

    def draw(self, _context):
        pass


TEST_CLASSES = (
    TEST_PT_no3d_dev,
    AGENT_BRIDGE_PT_panel,
    TEST_PT_other,
    TEST_PT_eyecones_internal_no3d_name,
)

for cls in TEST_CLASSES:
    bpy.utils.register_class(cls)

tab_filter.register()
try:
    assert numbered.apply_numbering()
    assert TEST_PT_no3d_dev.bl_category == "[1] NO3D Dev"
    assert AGENT_BRIDGE_PT_panel.bl_category == "Agent"
    assert TEST_PT_other.bl_category == "Other Test"

    assert tab_filter.apply_filter("no3d")
    assert TEST_PT_no3d_dev.is_registered
    assert not TEST_PT_other.is_registered
    assert not TEST_PT_eyecones_internal_no3d_name.is_registered

    assert tab_filter.apply_filter("")
    assert TEST_PT_other.is_registered
    assert TEST_PT_eyecones_internal_no3d_name.is_registered

    assert tab_filter.apply_filter("agnet")
    assert AGENT_BRIDGE_PT_panel.is_registered
    assert not TEST_PT_no3d_dev.is_registered
    assert not TEST_PT_other.is_registered

    assert tab_filter.apply_filter("")
    assert tab_filter.apply_filter("othr")
    assert TEST_PT_other.is_registered
    assert not TEST_PT_no3d_dev.is_registered
    assert tab_filter.apply_filter("")

    prop = bpy.types.WindowManager.bl_rna.properties.get(tab_filter.FILTER_PROPERTY)
    assert prop is not None
    assert prop.is_skip_save
    assert hasattr(bpy.ops.view3d, "no3d_type_sidebar_tab_filter")

    class FakeWorkspace:
        def __init__(self):
            self.status = ""

        def status_text_set(self, value):
            self.status = value

    class FakeArea:
        def tag_redraw(self):
            pass

    modal_context = SimpleNamespace(
        window_manager=bpy.context.window_manager,
        workspace=FakeWorkspace(),
        area=FakeArea(),
    )
    operator = SimpleNamespace(
        _finish=lambda _context: {"FINISHED"},
    )
    setattr(bpy.context.window_manager, tab_filter.FILTER_PROPERTY, "ag")
    event = SimpleNamespace(
        value="PRESS", type="BACK_SPACE", ascii="", ctrl=False, alt=False, oskey=False
    )
    assert tab_filter.NO3D_AD_OT_type_sidebar_tab_filter.modal(operator, modal_context, event) == {"RUNNING_MODAL"}
    assert getattr(bpy.context.window_manager, tab_filter.FILTER_PROPERTY) == "a"
    event = SimpleNamespace(
        value="PRESS", type="G", ascii="g", ctrl=False, alt=False, oskey=False
    )
    assert tab_filter.NO3D_AD_OT_type_sidebar_tab_filter.modal(operator, modal_context, event) == {"RUNNING_MODAL"}
    assert getattr(bpy.context.window_manager, tab_filter.FILTER_PROPERTY) == "ag"
    event = SimpleNamespace(
        value="PRESS", type="ESC", ascii="", ctrl=False, alt=False, oskey=False
    )
    assert tab_filter.NO3D_AD_OT_type_sidebar_tab_filter.modal(operator, modal_context, event) == {"FINISHED"}
    assert getattr(bpy.context.window_manager, tab_filter.FILTER_PROPERTY) == ""

    class FakeRow:
        def __init__(self):
            self.calls = []

        def prop(self, owner, prop, **kwargs):
            self.calls.append(("prop", owner, prop, kwargs))

        def operator(self, operator_id, **kwargs):
            self.calls.append(("operator", operator_id, kwargs))

    class FakeLayout:
        def __init__(self):
            self.row_value = FakeRow()

        def row(self, align=False):
            assert align
            return self.row_value

    layout = FakeLayout()
    header = type("Header", (), {"layout": layout})()
    tab_filter._draw_tool_header(header, bpy.context)
    assert layout.row_value.calls[0][0] == "prop"
    assert layout.row_value.calls[0][2] == tab_filter.FILTER_PROPERTY
    assert [call[1] for call in layout.row_value.calls[1:]] == [
        "view3d.no3d_clear_sidebar_tab_filter",
        "view3d.no3d_search_sidebar_tabs",
    ]

    stale_callback = lambda _self, _context: None
    stale_callback.__name__ = tab_filter._draw_tool_header.__name__
    stale_callback.__module__ = tab_filter.__name__
    bpy.types.VIEW3D_HT_tool_header.append(stale_callback)
    matching_callbacks = [
        callback
        for callback in bpy.types.VIEW3D_HT_tool_header.draw._draw_funcs
        if getattr(callback, "__name__", "") == "_draw_tool_header"
        and getattr(callback, "__module__", "") == tab_filter.__name__
    ]
    assert len(matching_callbacks) == 2
    tab_filter._remove_tool_header_callbacks()
    assert not any(
        getattr(callback, "__name__", "") == "_draw_tool_header"
        and getattr(callback, "__module__", "") == tab_filter.__name__
        for callback in bpy.types.VIEW3D_HT_tool_header.draw._draw_funcs
    )
    bpy.types.VIEW3D_HT_tool_header.append(tab_filter._draw_tool_header)
finally:
    tab_filter.unregister()
    numbered.restore_numbering()
    for cls in reversed(TEST_CLASSES):
        if cls.is_registered:
            bpy.utils.unregister_class(cls)

assert TEST_PT_no3d_dev.bl_category == "NO3D Dev"
assert AGENT_BRIDGE_PT_panel.bl_category == "Agent"
print("NPANEL_CHAOS_CONTROLS_OK")
