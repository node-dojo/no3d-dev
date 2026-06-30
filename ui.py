"""
No3d Asset Developer — UI panels and menus.

Asset Browser context menu, export panel, cleanup panel, and N-panel dev notes.
"""

import logging

import time

import bpy
from bpy.types import Menu, Panel

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
    """Shared draw body: extraction method picker + WIP auto-sync + Recents.

    Registered on multiple space types (3D Viewport, Asset Browser) so the
    same panel appears wherever you happen to be working.
    """
    layout = self.layout
    wm = context.window_manager

    box = layout.box()
    box.label(text="Extraction Method:", icon='PRESET')
    box.prop(wm, "no3d_extraction_method", text="")

    method = wm.no3d_extraction_method
    hint_box = layout.box()
    if method == "TEMPLATE_APPEND":
        hint_box.label(text="A - Template Append (subprocess)", icon='SETTINGS')
        hint_box.label(text="- Preserves Scene + METRIC/mm units")
        hint_box.label(text="- Strips smuggled assets")
        hint_box.label(text="- Requires current file saved")
    else:
        hint_box.label(text="B - Datablock Write (in-process)", icon='SCRIPT')
        hint_box.label(text="- libraries.write() - pose-lib native")
        hint_box.label(text="- No Scene/units in output")
        hint_box.label(text="- Transitive deps come along")

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

    # -- WIP Auto-Sync --
    layout.separator()
    wip_box = layout.box()
    header = wip_box.row()
    header.label(text="WIP Auto-Sync", icon='FILE_REFRESH')
    method_label = "Method A" if method == "TEMPLATE_APPEND" else "Method B"
    header.label(text=f"uses {method_label}")
    wip_box.prop(wm, "no3d_wip_folder", text="Folder")

    if not wip_sync.get_wip_folder():
        warn = wip_box.box()
        warn.alert = True
        warn.label(text="Set folder to enable auto-sync", icon='ERROR')
    else:
        toggles = wip_box.column(align=True)
        toggles.prop(wm, "no3d_wip_auto_mark")
        toggles.prop(wm, "no3d_wip_auto_save")
        toggles.prop(wm, "no3d_wip_auto_rename")

    sync_row = wip_box.row()
    sync_row.scale_y = 1.2
    sync_row.operator(
        "asset.sync_wip_all_no3d",
        text="Sync All Now",
        icon='FILE_REFRESH',
    )

    status = wip_sync.get_status()
    if status.get("msg"):
        ago = max(0, int(time.time() - status.get("ts", 0)))
        wip_box.label(text=f"{status['msg']} ({ago}s ago)", icon='INFO')

    # -- Recents --
    if wip_sync.get_wip_folder():
        recents_box = wip_box.box()
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


class NO3D_PT_extract_v3(Panel):
    """3D Viewport N-panel."""
    bl_label = "Asset Extraction (v3)"
    bl_idname = "NO3D_PT_extract_v3"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "No3D Dev"

    draw = _draw_extract_v3


class NO3D_PT_extract_v3_assetbrowser(Panel):
    """Same panel, mounted in the Asset Browser's right TOOL_PROPS column."""
    bl_label = "Asset Extraction (v3)"
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
# Registration
# ---------------------------------------------------------------------------

_classes = (
    NO3D_MT_asset_export_menu,
    NO3D_PT_asset_cleanup_panel,
    NO3D_PT_extract_v3,
    NO3D_PT_extract_v3_assetbrowser,
    NO3D_PT_dev_notes,
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


def unregister():
    global _appended_context_menu, _appended_details_panel

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
