"""
No3d Asset Developer — UI panels and menus.

Asset Browser context menu, export panel, cleanup panel, and N-panel dev notes.
"""

import logging

import time

import bpy
from bpy.types import Menu, Panel

from . import aspect_overlay
from . import editor_screenshot
from . import header_screenshots  # noqa: F401  (operators registered separately)
from . import viewport_format
from . import wip_sync
from .notes import note_manager

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Asset Browser menu & panels
# ---------------------------------------------------------------------------

class NO3D_MT_asset_export_menu(Menu):
    """NO3D Export Tools submenu"""
    bl_label = "NO3D Export Tools"
    bl_idname = "NO3D_MT_asset_export_menu"

    def draw(self, context):
        layout = self.layout
        layout.operator(
            "asset.export_active_no3d",
            text="Export Active Asset",
            icon='EXPORT',
        )
        layout.operator(
            "asset.export_all_no3d",
            text="Export All Assets",
            icon='EXPORT',
        )
        layout.separator()
        layout.operator(
            "asset.export_thumbnails_only_no3d",
            text="Export Thumbnails Only",
            icon='IMAGE_DATA',
        )


class NO3D_PT_asset_cleanup_panel(Panel):
    """NO3D Asset Cleanup panel in Asset Editor Tool Properties"""
    bl_label = "Asset Cleanup"
    bl_idname = "NO3D_PT_asset_cleanup_panel"
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_category = "No3D Dev"

    def draw(self, context):
        layout = self.layout

        # Get the active asset
        asset = None
        if hasattr(context, 'id') and context.id:
            candidate = context.id
            if hasattr(candidate, 'asset_data') and candidate.asset_data:
                asset = candidate

        if not asset and hasattr(context, 'active_object') and context.active_object:
            obj = context.active_object
            if hasattr(obj, 'asset_data') and obj.asset_data:
                asset = obj

        if not asset and hasattr(context, 'selected_objects'):
            for obj in context.selected_objects:
                if hasattr(obj, 'asset_data') and obj.asset_data:
                    asset = obj
                    break

        if not asset:
            box = layout.box()
            box.label(text="No asset selected", icon='INFO')
            box.label(text="Select an asset in the Asset Browser")
            box.label(text="to scan for dependencies")
            return

        # Asset Info
        box = layout.box()
        box.label(text="Selected Asset:", icon='ASSET_MANAGER')
        box.row().label(text=f"Name: {asset.name}")
        box.row().label(text=f"Type: {type(asset).__name__}")

        layout.separator()
        row = layout.row()
        row.scale_y = 1.2
        row.operator(
            "asset.scan_dependencies_no3d",
            text="Scan Dependencies",
            icon='VIEWZOOM',
        )

        # Dependencies list
        wm = context.window_manager
        dependencies = wm.get('no3d_asset_dependencies', [])

        if dependencies:
            layout.separator()
            box = layout.box()
            box.label(text=f"Dependencies Found: {len(dependencies)}", icon='ERROR')

            row = box.row()
            row.scale_y = 1.2
            row.operator(
                "asset.clean_all_dependencies_no3d",
                text="Clean All",
                icon='BRUSH_DATA',
            )

            layout.separator()

            for i, dep in enumerate(dependencies):
                dep_box = layout.box()
                dep_box.row().label(text=f"{i + 1}. {dep['dependency_name']}", icon='ERROR')
                dep_box.row().label(text=f"Type: {dep['type']}")

                if dep.get('relationship'):
                    dep_box.row().label(text=f"Relationship: {dep['relationship']}")
                if dep.get('node_name'):
                    dep_box.row().label(text=f"Node: {dep['node_name']}")
                if dep.get('modifier_name'):
                    dep_box.row().label(text=f"Modifier: {dep['modifier_name']}")

                row = dep_box.row()
                row.scale_y = 1.1

                if dep['action_available'] == 'isolate' and dep['type'] == 'NodeGroup':
                    op = row.operator(
                        "asset.isolate_node_group_no3d",
                        text="Isolate",
                        icon='DUPLICATE',
                    )
                    op.dependency_name = dep['dependency_name']
                    op.dependency_type = dep['dependency_type']
                    op.node_name = dep.get('node_name', '')
                    op.modifier_name = dep.get('modifier_name', '')

                if dep['action_available'] == 'remove':
                    op = row.operator(
                        "asset.remove_dependency_no3d",
                        text="Remove",
                        icon='X',
                    )
                    op.dependency_name = dep['dependency_name']
                    op.dependency_type = dep['dependency_type']
                    op.relationship = dep.get('relationship', '')
                    op.modifier_name = dep.get('modifier_name', '')
        else:
            scanned_asset = wm.get('no3d_scanned_asset_name', '')
            if scanned_asset == asset.name:
                box = layout.box()
                box.label(text="No problematic dependencies found", icon='CHECKMARK')
                box.label(text="Asset is ready for export")
            else:
                box = layout.box()
                box.label(text="Click 'Scan Dependencies' to check", icon='INFO')


# ---------------------------------------------------------------------------
# v3.0 — Method-selectable extraction panel (View3D N-panel)
# ---------------------------------------------------------------------------

def _draw_extract_v3(self, context):
    """Shared draw body for the No3d Asset Manager v3 panel.

    Layout (top → bottom):
      1. Sync All Now button (scale_y 1.2)
      2. Recents box (only when WIP folder is set)
      3. WIP Auto-Sync section (folder + 3 checkboxes + status)
      4. Extract Active Asset button (scale_y 1.3)
      5. Extract All Assets button (scale_y 1.3)

    Extraction Method dropdown is hidden — the property still exists in
    WindowManager (read by operators / wip_sync), defaulting to Method B.

    Registered on multiple space types (3D Viewport, Asset Browser) so the
    same panel appears wherever you happen to be working.
    """
    layout = self.layout
    wm = context.window_manager

    # Extraction method is hidden from the UI — Method B (Datablock Write) is the
    # sole exposed pipeline. Method A (Template Append) is retained in code and can
    # be re-enabled via `wm.no3d_extraction_method = 'TEMPLATE_APPEND'` in the console.
    wip_folder_set = bool(wip_sync.get_wip_folder())

    # 1. Sync All Now (outside the WIP box, no header above it)
    sync_row = layout.row()
    sync_row.scale_y = 1.2
    sync_row.operator(
        "asset.sync_wip_all_no3d",
        text="Sync All Now",
        icon='FILE_REFRESH',
    )

    # 2. Recents (only when a WIP folder is configured)
    if wip_folder_set:
        recents_box = layout.box()
        header = recents_box.row(align=True)
        header.label(text="Recents", icon='SORTTIME')
        header.prop(wm, "no3d_wip_recent_count", text="")
        limit = int(getattr(wm, "no3d_wip_recent_count", 8))
        recents = wip_sync.list_recent_folders(limit)
        if not recents:
            recents_box.label(text="No assets synced yet", icon='INFO')
        else:
            now = time.time()
            col = recents_box.column(align=True)
            for name, mtime in recents:
                age = now - mtime
                if age < 60:
                    ago_str = f"{int(age)}s"
                elif age < 3600:
                    ago_str = f"{int(age / 60)}m"
                elif age < 86400:
                    ago_str = f"{int(age / 3600)}h"
                else:
                    ago_str = f"{int(age / 86400)}d"
                row = col.row(align=True)
                op = row.operator(
                    "asset.open_wip_folder_no3d",
                    text=f"{name}",
                    icon='FILE_FOLDER',
                    emboss=False,
                )
                op.folder_name = name
                row.label(text=ago_str)

    # 3. WIP Auto-Sync section
    wip_box = layout.box()
    header = wip_box.row()
    header.label(text="WIP Auto-Sync", icon='FILE_REFRESH')
    wip_box.prop(wm, "no3d_wip_folder", text="Folder")

    if not wip_folder_set:
        warn = wip_box.box()
        warn.alert = True
        warn.label(text="Set folder to enable auto-sync", icon='ERROR')
    else:
        toggles = wip_box.column(align=True)
        toggles.prop(wm, "no3d_wip_auto_mark")
        toggles.prop(wm, "no3d_wip_auto_save")
        toggles.prop(wm, "no3d_wip_auto_rename")

        status = wip_sync.get_status()
        if status.get("msg"):
            ago = max(0, int(time.time() - status.get("ts", 0)))
            wip_box.label(text=f"{status['msg']} ({ago}s ago)", icon='INFO')

    # 4 + 5. Extract buttons (scale_y 1.3)
    layout.separator()
    col = layout.column(align=True)
    col.scale_y = 1.3
    col.operator(
        "asset.extract_v3_active_no3d",
        text="Extract Active Asset",
        icon='EXPORT',
    )
    col.operator(
        "asset.extract_v3_all_no3d",
        text="Extract All Assets",
        icon='PACKAGE',
    )


class NO3D_PT_extract_v3(Panel):
    """3D Viewport N-panel."""
    bl_label = "No3d Asset Manager v3"
    bl_idname = "NO3D_PT_extract_v3"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "No3D Dev"

    draw = _draw_extract_v3


class NO3D_PT_extract_v3_assetbrowser(Panel):
    """Same panel, mounted in the Asset Browser's right TOOL_PROPS column."""
    bl_label = "No3d Asset Manager v3"
    bl_idname = "NO3D_PT_extract_v3_assetbrowser"
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_category = "No3D Dev"

    @classmethod
    def poll(cls, context):
        # Only show in Asset Browser mode, not regular File Browser.
        sd = getattr(context.space_data, "browse_mode", None)
        return sd == 'ASSETS' if sd is not None else True

    draw = _draw_extract_v3


# ---------------------------------------------------------------------------
# Dev Notes panel (Phase 3) — View3D N-panel
# ---------------------------------------------------------------------------

class NO3D_PT_dev_notes(Panel):
    """Quick developer notes panel in the 3D Viewport sidebar"""
    bl_label = "Dev Notes"
    bl_idname = "NO3D_PT_dev_notes"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "No3D Dev"

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager

        # Determine asset context
        asset_name = "Global"
        if hasattr(context, 'active_object') and context.active_object:
            obj = context.active_object
            if hasattr(obj, 'asset_data') and obj.asset_data:
                asset_name = obj.name

        # Context label
        box = layout.box()
        box.label(text=f"Asset: {asset_name}", icon='ASSET_MANAGER')

        # Input
        layout.separator()
        row = layout.row(align=True)
        row.prop(wm.no3d_note_input, "text", text="")
        row.operator("no3d.add_dev_note", text="", icon='ADD')

        # Notes list
        notes = note_manager.get_notes(asset_name)
        if notes:
            layout.separator()
            box = layout.box()
            box.label(text=f"Notes ({len(notes)}):", icon='TEXT')
            col = box.column(align=True)
            for timestamp, text in notes:
                col.label(text=f"[{timestamp}] {text}")

            layout.separator()
            layout.operator("no3d.clear_dev_notes", text="Clear Notes", icon='X')
        else:
            layout.label(text="No notes yet", icon='INFO')

        # Show all assets with notes
        all_names = note_manager.get_all_asset_names()
        other_names = [n for n in all_names if n != asset_name]
        if other_names:
            layout.separator()
            box = layout.box()
            box.label(text="Other assets with notes:", icon='OUTLINER_OB_GROUP_INSTANCE')
            for name in other_names:
                count = len(note_manager.get_notes(name))
                box.label(text=f"  {name} ({count})")


# ---------------------------------------------------------------------------
# Context menu draw functions
# ---------------------------------------------------------------------------

def draw_asset_browser_context_menu(self, context):
    """Add NO3D export options to Asset Browser context menu."""
    layout = self.layout
    layout.separator()
    layout.operator(
        "asset.open_location_no3d",
        text="Open File Location",
        icon='FILE_FOLDER',
    )
    layout.separator()
    layout.menu("NO3D_MT_asset_export_menu", text="NO3D Export Tools", icon='TOOL_SETTINGS')


def draw_asset_browser_details_panel(self, context):
    """Add button to Asset Browser details panel."""
    if hasattr(context, 'id') and context.id:
        asset = context.id
        if hasattr(asset, 'asset_data') and asset.asset_data:
            layout = self.layout
            layout.separator()
            row = layout.row()
            row.scale_y = 1.2
            row.operator(
                "asset.open_location_no3d",
                text="Open File Location",
                icon='FILE_FOLDER',
            )


# ---------------------------------------------------------------------------
# 3D Viewport — Screenshot panel
# ---------------------------------------------------------------------------

class NO3D_PT_viewport_screenshot(Panel):
    """Capture transparent PNGs of the 3D viewport."""
    bl_label = "Viewport Screenshot"
    bl_idname = "NO3D_PT_viewport_screenshot"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "No3D Dev"

    def draw(self, context):
        layout = self.layout
        addon = context.preferences.addons.get("no3d_asset_developer")
        prefs = addon.preferences if addon else None

        col = layout.column(align=True)
        if prefs is not None:
            col.label(text="Output folder:")
            col.prop(prefs, "node_screenshot_path", text="")
            if not (prefs.node_screenshot_path or "").strip():
                blend = bpy.data.filepath
                fallback = (
                    "Current .blend folder" if blend
                    else "~/Downloads (no .blend saved)"
                )
                col.label(text=f"→ {fallback}", icon='INFO')

        # Capture method dropdown + tradeoff hints + multiplier
        if prefs is not None:
            layout.separator()
            method_box = layout.box()
            method_box.label(text="Capture Method:", icon='RESTRICT_RENDER_OFF')
            method_box.prop(prefs, "viewport_capture_method", text="")

            method = prefs.viewport_capture_method

            # Multiplier — disabled for screen-pixel-only methods
            mult_row = method_box.row(align=True)
            mult_row.enabled = method not in {"SCREEN_CAPTURE", "WORLD_SWAP_DIFF"}
            mult_row.prop(prefs, "viewport_capture_resolution_multiplier", slider=True)

            # Per-method tradeoff hint
            hint = method_box.column(align=True)
            hint.scale_y = 0.85
            if method == "RENDER_OPENGL":
                hint.label(text="Alpha: no   Gizmos: no   Multiplier: yes", icon='INFO')
                hint.label(text="Sharp Solid-mode render. Default.")
            elif method == "OFFSCREEN_SOLID":
                hint.label(text="Alpha: yes  Gizmos: no   Multiplier: yes", icon='INFO')
                hint.label(text="Forces Solid shading.")
            elif method == "OFFSCREEN_MATERIAL":
                hint.label(text="Alpha: yes  Gizmos: no   Multiplier: yes", icon='INFO')
                hint.label(text="Uses current shading; HDRI visible.")
                hint.label(text="Glass/transmissive may have alpha holes.")
            elif method == "SCREEN_CAPTURE":
                hint.label(text="Alpha: no   Gizmos: yes  Multiplier: native", icon='INFO')
                hint.label(text="Crops the full-window screenshot.")
            elif method == "CRYPTOMATTE_OFFSCREEN_MASK":
                hint.label(text="Alpha: yes  Gizmos: yes  Multiplier: yes", icon='INFO')
                hint.label(text="Two-pass: solid-white mask + screen RGB.")
            elif method == "WORLD_SWAP_DIFF":
                hint.label(text="Alpha: yes  Gizmos: yes  Multiplier: native", icon='INFO')
                hint.label(text="Magenta/green diff matte.")
                hint.label(text="Falls back if world has no 'Solid Color'.")

        layout.separator()

        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator(
            "no3d.viewport_screenshot_visible",
            text="Capture Visible Area",
            icon='IMAGE_DATA',
        )
        col.operator(
            "no3d.viewport_screenshot_region",
            text="Capture Region…",
            icon='SELECT_SET',
        )
        col.operator(
            "no3d.viewport_screenshot_thumbnail",
            text="Capture Thumbnail…",
            icon='IMAGE_REFERENCE',
        )

        if prefs is not None:
            layout.separator()
            layout.prop(prefs, "viewport_screenshot_keep_gizmos")
            row = layout.row(align=True)
            row.label(text="Thumbnail margin:")
            row.prop(prefs, "thumbnail_margin", text="", slider=True)

        layout.separator()
        layout.label(text="Saves PNG, copies to clipboard.", icon='INFO')


# ---------------------------------------------------------------------------
# 3D Viewport — Paste Clipboard as Plane
# ---------------------------------------------------------------------------

class NO3D_PT_paste_clipboard(Panel):
    """Paste a clipboard image as a textured plane in the 3D viewport."""
    bl_label = "Paste Clipboard as Plane"
    bl_idname = "NO3D_PT_paste_clipboard"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "No3D Dev"

    def draw(self, context):
        layout = self.layout
        addon = context.preferences.addons.get("no3d_asset_developer")
        prefs = addon.preferences if addon else None

        if prefs is not None:
            row = layout.row(align=True)
            row.label(text="Long edge:")
            row.prop(prefs, "paste_plane_long_edge_mm", text="")

        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator(
            "no3d.paste_clipboard_plane",
            text="Paste Clipboard as Plane",
            icon='IMAGE_REFERENCE',
        )
        col.operator(
            "no3d.orient_z_to_viewport",
            text="Orient Selected Z to Viewport",
            icon='ORIENTATION_VIEW',
        )



# ---------------------------------------------------------------------------
# 3D Viewport — Editor (any-area) Screenshot panel
# ---------------------------------------------------------------------------


class NO3D_PT_editor_screenshot(Panel):
    """Capture any single editor area as a clean PNG."""
    bl_label = "Editor Screenshot"
    bl_idname = "NO3D_PT_editor_screenshot"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "No3D Dev"

    def draw(self, context):
        layout = self.layout
        addon = context.preferences.addons.get("no3d_asset_developer")
        prefs = addon.preferences if addon else None

        col = layout.column(align=True)
        col.label(text="Pick an editor:")
        editors = list(editor_screenshot.list_visible_editors())
        if not editors:
            col.label(text="No editors found", icon='ERROR')
        else:
            for token, label, _, _, _, _, _ in editors:
                op = col.operator(
                    "no3d.editor_screenshot",
                    text=label,
                    icon='WINDOW',
                )
                op.area_token = token

        layout.separator()

        if prefs is not None:
            box = layout.box()
            box.prop(prefs, "editor_capture_round_corners")
            row = box.row()
            row.enabled = prefs.editor_capture_round_corners
            row.prop(prefs, "editor_capture_corner_radius", slider=True)

        layout.separator()
        layout.label(text="Saves PNG, copies to clipboard.", icon='INFO')


# ---------------------------------------------------------------------------
# 3D Viewport — Match-to-Preset panel
# ---------------------------------------------------------------------------


def _gcd(a, b):
    while b:
        a, b = b, a % b
    return max(1, a)


class NO3D_PT_viewport_format(Panel):
    """Resize the Blender window to a content-format aspect ratio."""
    bl_label = "Viewport Format"
    bl_idname = "NO3D_PT_viewport_format"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "No3D Dev"

    def draw(self, context):
        layout = self.layout
        win = context.window
        screen = win.screen

        # Show the active 3D viewport's current dims + aspect
        area = context.area if context.area and context.area.type == 'VIEW_3D' else None
        if area is None:
            v3ds = [a for a in screen.areas if a.type == 'VIEW_3D']
            v3ds.sort(key=lambda a: a.width * a.height, reverse=True)
            area = v3ds[0] if v3ds else None

        info = layout.box()
        if area is not None:
            cur_w = int(area.width)
            cur_h = int(area.height)
            g = _gcd(cur_w, cur_h)
            info.label(text="Active viewport size:", icon='WINDOW')
            info.label(text=f"  {cur_w} x {cur_h}  ({cur_w // g}:{cur_h // g})")
        else:
            info.label(text="No 3D viewport in this workspace", icon='ERROR')

        layout.separator()
        col = layout.column(align=True)
        col.scale_y = 1.2
        col.label(text="Reshape viewport to aspect:")
        for key, label, _desc, _aw, _ah in viewport_format.PRESETS:
            op = col.operator(
                "no3d.apply_viewport_preset",
                text=label,
                icon='OUTPUT',
            )
            op.preset = key

        layout.separator()
        sub = layout.column(align=True)
        sub.scale_y = 0.85
        sub.label(text="Reshapes one 3D viewport area in place.", icon='INFO')
        sub.label(text="Neighbors absorb the change. Window stays put.")


# ---------------------------------------------------------------------------
# 3D Viewport — Aspect Overlay panel
# ---------------------------------------------------------------------------


class NO3D_PT_aspect_overlay(Panel):
    """Toggle and configure the screen-space aspect-ratio overlay."""
    bl_label = "Aspect Overlay"
    bl_idname = "NO3D_PT_aspect_overlay"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "No3D Dev"

    def draw(self, context):
        aspect_overlay.draw_aspect_overlay_section(self.layout, context)


# ---------------------------------------------------------------------------
# Node Editor — Screenshot panel
# ---------------------------------------------------------------------------

class NO3D_PT_node_screenshot(Panel):
    """Capture transparent PNGs of the node editor."""
    bl_label = "Node Screenshot"
    bl_idname = "NO3D_PT_node_screenshot"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "No3D Dev"

    def draw(self, context):
        layout = self.layout
        addon = context.preferences.addons.get("no3d_asset_developer")
        prefs = addon.preferences if addon else None

        col = layout.column(align=True)
        if prefs is not None:
            col.label(text="Output folder:")
            col.prop(prefs, "node_screenshot_path", text="")
            if not (prefs.node_screenshot_path or "").strip():
                blend = bpy.data.filepath
                fallback = (
                    "Current .blend folder" if blend
                    else "~/Downloads (no .blend saved)"
                )
                col.label(text=f"→ {fallback}", icon='INFO')

        layout.separator()

        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator(
            "no3d.node_screenshot_visible",
            text="Capture Visible Area",
            icon='IMAGE_DATA',
        )
        col.operator(
            "no3d.node_screenshot_region",
            text="Capture Region…",
            icon='SELECT_SET',
        )
        col.operator(
            "no3d.node_screenshot_thumbnail",
            text="Capture Thumbnail…",
            icon='IMAGE_REFERENCE',
        )

        if prefs is not None:
            layout.separator()
            row = layout.row(align=True)
            row.label(text="Thumbnail margin:")
            row.prop(prefs, "thumbnail_margin", text="", slider=True)

        layout.separator()
        layout.label(text="Saves transparent PNG, copies to clipboard.", icon='INFO')


# ---------------------------------------------------------------------------
# Header screenshot buttons — appended to editor header types
# ---------------------------------------------------------------------------

def draw_view3d_header_screenshot(self, context):
    layout = self.layout
    # N-panel button first (left of the area-screenshot button).
    layout.operator("no3d.viewport_npanel_screenshot", text="", icon='EVENT_N')
    layout.operator("no3d.header_area_screenshot", text="", icon='CAMERA_DATA')


def draw_outliner_header_screenshot(self, context):
    layout = self.layout
    layout.operator("no3d.header_area_screenshot", text="", icon='CAMERA_DATA')


def draw_properties_header_screenshot(self, context):
    layout = self.layout
    layout.operator("no3d.header_area_screenshot", text="", icon='CAMERA_DATA')


def draw_file_header_screenshot(self, context):
    # FILEBROWSER_HT_header serves the File Browser, the Asset Browser, AND
    # transient file-select popups, and it draws in more than one region.
    # Only draw the button in the main header region, and skip the temporary
    # file-select dialogs (those have no persistent area worth capturing).
    region = getattr(context, "region", None)
    if region is not None and region.type != 'HEADER':
        return
    area = getattr(context, "area", None)
    if area is None or area.type != 'FILE_BROWSER':
        return
    self.layout.operator("no3d.header_area_screenshot", text="", icon='CAMERA_DATA')


def draw_node_header_screenshot(self, context):
    layout = self.layout
    layout.operator("no3d.header_area_screenshot", text="", icon='CAMERA_DATA')


# (header_type_name, draw_function) pairs — appended on register, removed on
# unregister. Each is wrapped in try/except so a missing class doesn't take
# down the whole registration.
_HEADER_APPENDS = (
    ("VIEW3D_HT_header", draw_view3d_header_screenshot),
    ("OUTLINER_HT_header", draw_outliner_header_screenshot),
    ("PROPERTIES_HT_header", draw_properties_header_screenshot),
    # Blender 5.x renamed the file/asset browser header to FILEBROWSER_HT_header
    # (the old FILE_HT_header no longer exists). This single header serves both
    # the File Browser and the Asset Browser, so one entry covers both.
    ("FILEBROWSER_HT_header", draw_file_header_screenshot),
    ("NODE_HT_header", draw_node_header_screenshot),
)

# Names of header types that successfully had their draw fn appended — used
# at unregister time so we only attempt to remove what we actually added.
_appended_headers = []


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_classes = (
    NO3D_MT_asset_export_menu,
    NO3D_PT_asset_cleanup_panel,
    NO3D_PT_extract_v3,
    NO3D_PT_extract_v3_assetbrowser,
    NO3D_PT_dev_notes,
    NO3D_PT_node_screenshot,
    NO3D_PT_viewport_screenshot,
    NO3D_PT_editor_screenshot,
    # NO3D_PT_viewport_format intentionally disabled — class kept for re-enable.
    NO3D_PT_aspect_overlay,
    NO3D_PT_paste_clipboard,
)

# Menu types to try for context menu appending (varies by Blender version)
_CONTEXT_MENU_TYPES = (
    "ASSETBROWSER_MT_context_menu",
    "ASSETBROWSER_MT_asset",
    "ASSETBROWSER_MT_asset_context_menu",
)

_DETAILS_PANEL_TYPES = (
    "ASSETBROWSER_PT_asset_details",
    "ASSETBROWSER_PT_sidebar",
)

_appended_context_menu = None
_appended_details_panel = None


def register():
    global _appended_context_menu, _appended_details_panel

    for cls in _classes:
        bpy.utils.register_class(cls)

    # Append to Asset Browser context menu
    for name in _CONTEXT_MENU_TYPES:
        menu_cls = getattr(bpy.types, name, None)
        if menu_cls is not None:
            try:
                menu_cls.append(draw_asset_browser_context_menu)
                _appended_context_menu = name
                break
            except Exception as exc:
                log.warning("Could not append to %s: %s", name, exc)
    else:
        log.warning("Could not find Asset Browser context menu to append to")

    # Append to Asset Browser details panel
    for name in _DETAILS_PANEL_TYPES:
        panel_cls = getattr(bpy.types, name, None)
        if panel_cls is not None:
            try:
                panel_cls.append(draw_asset_browser_details_panel)
                _appended_details_panel = name
                break
            except Exception as exc:
                log.warning("Could not append to %s: %s", name, exc)
    else:
        log.warning("Could not find Asset Browser details panel to append to")

    # Append screenshot buttons to editor headers. Each append is isolated so
    # a single missing header class doesn't take down the rest.
    _appended_headers.clear()
    for header_name, draw_fn in _HEADER_APPENDS:
        header_cls = getattr(bpy.types, header_name, None)
        if header_cls is None:
            log.warning("Header type %s not found — skipping screenshot button", header_name)
            continue
        try:
            header_cls.append(draw_fn)
            _appended_headers.append((header_name, draw_fn))
        except Exception as exc:
            log.warning("Could not append screenshot button to %s: %s", header_name, exc)


def unregister():
    global _appended_context_menu, _appended_details_panel

    # Remove header screenshot button appends
    for header_name, draw_fn in list(_appended_headers):
        header_cls = getattr(bpy.types, header_name, None)
        if header_cls is not None:
            try:
                header_cls.remove(draw_fn)
            except ValueError:
                pass
    _appended_headers.clear()

    # Remove context menu append
    if _appended_context_menu:
        menu_cls = getattr(bpy.types, _appended_context_menu, None)
        if menu_cls is not None:
            try:
                menu_cls.remove(draw_asset_browser_context_menu)
            except ValueError:
                pass
        _appended_context_menu = None

    # Remove details panel append
    if _appended_details_panel:
        panel_cls = getattr(bpy.types, _appended_details_panel, None)
        if panel_cls is not None:
            try:
                panel_cls.remove(draw_asset_browser_details_panel)
            except ValueError:
                pass
        _appended_details_panel = None

    for cls in reversed(_classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
