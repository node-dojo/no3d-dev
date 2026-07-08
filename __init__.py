bl_info = {
    "name": "No3d Asset Developer",
    "author": "NO3D Tools",
    "version": (3, 2, 0),
    "blender": (5, 0, 0),
    "location": "Asset Browser > Context Menu | 3D Viewport > N-Panel > No3D Dev",
    "description": "Export marked assets as clean, individual .blend files with frontmatter, thumbnails, and dev notes. WIP folder auto-sync.",
    "category": "Asset",
    "doc_url": "",
    "tracker_url": "",
}

import datetime
import os

import bpy
from bpy.types import AddonPreferences
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    StringProperty,
)
from . import aspect_overlay
from . import claude_pair
from . import save_reload
from . import clipboard_paste
from . import repo_registration
from . import editor_screenshot
from . import header_screenshots
from . import node_screenshot
from . import operators
from . import ui
from . import viewport_format
from . import viewport_screenshot
from . import wip
from . import wip_sync
from .notes import note_manager


# NOTE: Method A (TEMPLATE_APPEND) is retained in code but no longer exposed in
# the UI — Method B (DATABLOCK_WRITE) is the sole user-facing pipeline. This enum
# is kept so the dispatcher and the console escape hatch still resolve both
# identifiers; the picker was removed from ui.py (see _draw_extract_v3).
EXTRACTION_METHOD_ITEMS = [
    (
        "TEMPLATE_APPEND",
        "Method A — Template Append",
        "Subprocess: opens _export_template.blend, appends the asset, strips smuggled markings, "
        "purges orphans, saves. Preserves scene and METRIC/mm units. Default for production.",
    ),
    (
        "DATABLOCK_WRITE",
        "Method B — Datablock Write",
        "In-process: bpy.data.libraries.write({asset}). Pose-library-native. No subprocess, no "
        "template. Faster. Output has no Scene/units; transitive deps come along.",
    ),
]


class NO3D_AddonPreferences(AddonPreferences):
    """Add-on preferences for No3d Asset Developer"""
    bl_idname = __name__

    default_vendor: StringProperty(
        name="Default Vendor",
        description="Default vendor name for exported assets",
        default="The Well Tarot",
    )

    default_product_type: StringProperty(
        name="Default Product Type",
        description="Default product type for exported assets",
        default="Blender Add-on",
    )

    export_library_path: StringProperty(
        name="Export Library Path",
        description="Default export directory for assets",
        subtype='DIR_PATH',
        default="",
    )

    node_screenshot_path: StringProperty(
        name="Node Screenshot Folder",
        description=(
            "Where transparent node-editor screenshots are saved. "
            "Empty = current .blend's folder, fall back to ~/Downloads"
        ),
        subtype='DIR_PATH',
        default="",
    )

    thumbnail_margin: FloatProperty(
        name="Thumbnail Margin",
        description=(
            "Outer margin guide for thumbnail capture, as a fraction of the "
            "square's side. 0.25 = inner safe-area is half the outer size."
        ),
        default=0.25,
        min=0.0,
        max=0.49,
        precision=2,
        subtype='FACTOR',
    )

    viewport_screenshot_keep_gizmos: BoolProperty(
        name="Keep Gizmos in Capture",
        description=(
            "When capturing the 3D viewport, keep gizmos (move/rotate/scale "
            "handles, light cones, camera frustums) visible in the output. "
            "Other overlays (grid, cursor, outlines) are still hidden. "
            "Note: OFFSCREEN_* methods cannot show gizmos at all (gizmos "
            "live in screen pixels only) — toggle is a no-op for those."
        ),
        default=False,
    )

    viewport_capture_method: EnumProperty(
        name="Viewport Capture Method",
        description=(
            "How the 3D viewport screenshot is rendered. Each method "
            "trades off transparency, gizmos, HDRI, and resolution differently."
        ),
        items=[
            (
                "RENDER_OPENGL",
                "OpenGL Render (default, sharp, no alpha)",
                "bpy.ops.render.opengl at multiplier resolution. No transparency. Clean and sharp.",
            ),
            (
                "OFFSCREEN_SOLID",
                "Offscreen Solid (sharp + alpha, no gizmos)",
                "GPU offscreen draw_view3d with draw_background=False. Native alpha, no gizmos.",
            ),
            (
                "OFFSCREEN_MATERIAL",
                "Offscreen Material/Rendered (HDRI + alpha)",
                "Same as Offscreen Solid but uses current viewport shading. Some materials may have partial-alpha holes.",
            ),
            (
                "SCREEN_CAPTURE",
                "Screen Capture (HDRI + gizmos, no alpha)",
                "Full-window screenshot cropped to viewport. No transparency. Includes everything you see.",
            ),
            (
                "CRYPTOMATTE_OFFSCREEN_MASK",
                "Cryptomatte Mask + Screen RGB (gizmos + alpha)",
                "Two-pass: flat-white solid mask + screen-capture RGB, composited. Best for transparent thumbnails with gizmos.",
            ),
            (
                "WORLD_SWAP_DIFF",
                "World Swap Difference Matte",
                "Magenta/green world swap, difference-matte extraction. Lower fidelity inside glossy reflections.",
            ),
        ],
        default="RENDER_OPENGL",
    )

    viewport_capture_resolution_multiplier: IntProperty(
        name="Resolution Multiplier",
        description=(
            "Multiply viewport dimensions by this factor for the capture. "
            "2x ~ Retina-sharp; 4x = oversampled. Methods that capture screen "
            "pixels (SCREEN_CAPTURE, WORLD_SWAP_DIFF) ignore this."
        ),
        default=2,
        min=1,
        max=4,
    )

    editor_capture_round_corners: BoolProperty(
        name="Round Outer Corners",
        description=(
            "When capturing an editor area, fade out the corners that touch "
            "the OS window's outer edge so the screenshot matches the macOS "
            "rounded-window look. Inner corners (adjacent to other editors) "
            "stay square"
        ),
        default=True,
    )

    editor_capture_corner_radius: IntProperty(
        name="Corner Radius (px)",
        description=(
            "Radius of the rounded fade at outer corners, in logical pixels. "
            "macOS Sequoia uses ~10 px. Set 0 to disable"
        ),
        default=10,
        min=0,
        max=40,
    )

    paste_plane_long_edge_mm: FloatProperty(
        name="Paste Plane Long Edge (mm)",
        description=(
            "When pasting a clipboard image as a plane, the long edge of "
            "the plane will be this many millimeters. The short edge is "
            "scaled to preserve the image's aspect ratio. Always millimeters, "
            "regardless of scene length units."
        ),
        default=50.0,
        min=0.1,
        max=10000.0,
        precision=2,
    )

    # ----- Aspect Overlay -----
    aspect_snap_enabled: BoolProperty(
        name="Magnetic Snap on Resize",
        description=(
            "When you finish dragging an editor edge, snap the result to "
            "the nearest enabled aspect-ratio preset if it's within the "
            "snap threshold"
        ),
        default=True,
    )
    aspect_snap_threshold_px: IntProperty(
        name="Snap Threshold (px)",
        description=(
            "How close (in logical pixels) the resulting area dimension "
            "must be to a preset's exact aspect for the snap to fire. "
            "0 disables"
        ),
        default=12,
        min=0,
        max=50,
    )
    show_preset_9_16: BoolProperty(
        name="Show Portrait 9:16",
        description="Draw the 9:16 preset rectangle in the overlay",
        default=True,
    )
    show_preset_4_5: BoolProperty(
        name="Show Feed 4:5",
        description="Draw the 4:5 preset rectangle in the overlay",
        default=True,
    )
    show_preset_1_1: BoolProperty(
        name="Show Square 1:1",
        description="Draw the 1:1 preset rectangle in the overlay",
        default=True,
    )
    show_preset_16_9: BoolProperty(
        name="Show Landscape 16:9",
        description="Draw the 16:9 preset rectangle in the overlay",
        default=True,
    )
    show_preset_4_3: BoolProperty(
        name="Show Hero/Banner 4:3",
        description=(
            "Draw the 4:3 preset rectangle in the overlay. Product-listing "
            "target: no3dtools Hero / Banner (960×720)"
        ),
        default=True,
    )
    show_preset_og_1_91: BoolProperty(
        name="Show Social/OG 1.91:1",
        description=(
            "Draw the 1.91:1 (1200×630) preset rectangle in the overlay. "
            "Product-listing target: Gumroad & no3dtools Social / OG image"
        ),
        default=True,
    )
    aspect_custom_presets: CollectionProperty(
        type=aspect_overlay.NO3D_AspectCustomPreset,
        name="Custom Aspect Presets",
        description="User-defined aspect-ratio presets",
    )
    aspect_custom_presets_index: IntProperty(
        name="Active Custom Preset",
        default=0,
    )

    aspect_section_snap_expanded: BoolProperty(
        name="Magnetic Snap section expanded",
        default=True,
    )
    aspect_section_builtin_expanded: BoolProperty(
        name="Built-in Presets section expanded",
        default=True,
    )
    aspect_section_custom_expanded: BoolProperty(
        name="Custom Presets section expanded",
        default=True,
    )

    # ----- Save & Reload (folded from the standalone add-on) -----
    save_folder: StringProperty(
        name="Save folder",
        description=(
            "Folder to save iteration .blend files into. "
            "Leave blank to save next to the current .blend file."
        ),
        default="",
        subtype="DIR_PATH",
    )
    iteration_digits: IntProperty(
        name="Iteration digits",
        description="Zero-padding width for the iteration suffix (e.g. 3 -> .001)",
        default=3, min=2, max=6,
    )
    confirm_before_restart: BoolProperty(
        name="Confirm before restart",
        description="Show a confirmation popup before saving and relaunching Blender",
        default=False,
    )

    # ----- Claude Pair (folded from the standalone add-on) -----
    scratch_dir: StringProperty(
        name="Scratch directory",
        description="Working directory used when the blend file has not been saved",
        default=str(os.path.join(os.path.expanduser("~"), "Desktop")),
        subtype="DIR_PATH",
    )
    claude_command: StringProperty(
        name="Claude command",
        description="Shell command to launch Claude Code in the paired terminal",
        default="claude",
    )
    claude_extra_args: StringProperty(
        name="Extra args",
        description="Additional arguments appended to the claude command (e.g. --model opus)",
        default="",
    )
    claude_auto_start: BoolProperty(
        name="Auto-start Claude",
        description="Run claude immediately in the spawned terminal. Disable to leave a plain shell open.",
        default=True,
    )
    auto_write_permissions: BoolProperty(
        name="Drop project permissions on pair",
        description="Write .claude/settings.local.json into the pair's cwd when pairing (only if absent)",
        default=True,
    )
    mcp_host: StringProperty(
        name="MCP host",
        description="Host the official MCP add-on binds to. localhost is correct in nearly all cases.",
        default="localhost",
    )
    port_range_start: IntProperty(
        name="Port range start",
        description="First port to try when scanning for a free port",
        default=9876, min=1024, max=65535,
    )
    port_range_end: IntProperty(
        name="Port range end",
        description="Last port to try when scanning for a free port",
        default=9999, min=1024, max=65535,
    )
    start_server_on_load: BoolProperty(
        name="Start MCP server on Blender startup",
        description=(
            "Automatically start the official MCP server after Blender loads a .blend "
            "file. Useful when paired with 'Re-pair & Resume' — the server is up before "
            "the user re-attaches Claude."
        ),
        default=False,
    )
    iterm_open_as: EnumProperty(
        name="Open as",
        description="Spawn a new iTerm2 window or a new tab in the front window",
        items=[
            ("WINDOW", "New window", "Open a fresh iTerm2 window"),
            ("TAB", "New tab", "Open a tab in the front iTerm2 window (falls back to window)"),
        ],
        default="WINDOW",
    )
    iterm_profile: StringProperty(
        name="iTerm2 profile",
        description="iTerm2 profile name to use. Leave blank for the default profile.",
        default="",
    )
    verbose_logging: BoolProperty(
        name="Verbose logging",
        description="Print pair lifecycle events to the system console",
        default=False,
    )

    def draw(self, context):
        layout = self.layout

        # Version Information
        box = layout.box()
        box.label(text="Version Information", icon='INFO')
        row = box.row()
        row.label(text=f"Version: {'.'.join(map(str, bl_info['version']))}")
        try:
            mtime = os.path.getmtime(__file__)
            stamp = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            box.row().label(text=f"Last updated: {stamp}")
        except OSError:
            pass

        layout.separator()

        # Export Defaults
        box = layout.box()
        box.label(text="Export Defaults", icon='EXPORT')
        box.prop(self, "default_vendor")
        box.prop(self, "default_product_type")
        box.prop(self, "export_library_path")

        layout.separator()

        # Node Screenshot
        box = layout.box()
        box.label(text="Node Screenshot", icon='IMAGE_DATA')
        box.prop(self, "node_screenshot_path")
        box.label(
            text="Empty = save next to current .blend (or ~/Downloads if unsaved)",
            icon='INFO',
        )
        box.prop(self, "thumbnail_margin", slider=True)

        layout.separator()

        # Viewport Capture
        box = layout.box()
        box.label(text="Viewport Capture", icon='RESTRICT_RENDER_OFF')
        box.prop(self, "viewport_capture_method", text="Method")
        box.prop(self, "viewport_capture_resolution_multiplier", slider=True)
        box.prop(self, "viewport_screenshot_keep_gizmos")
        box.label(
            text="OFFSCREEN_* methods cannot show gizmos (gizmos live in screen pixels)",
            icon='INFO',
        )

        layout.separator()

        # Editor Screenshot
        box = layout.box()
        box.label(text="Editor Screenshot", icon='WINDOW')
        box.prop(self, "editor_capture_round_corners")
        sub = box.row()
        sub.enabled = self.editor_capture_round_corners
        sub.prop(self, "editor_capture_corner_radius", slider=True)

        layout.separator()

        # Clipboard Paste
        box = layout.box()
        box.label(text="Paste Clipboard as Plane", icon='IMAGE_REFERENCE')
        box.prop(self, "paste_plane_long_edge_mm")

        layout.separator()

        # Save & Reload
        box = layout.box()
        box.label(text="Save & Reload", icon="FILE_REFRESH")
        box.prop(self, "save_folder")
        box.prop(self, "iteration_digits")
        box.prop(self, "confirm_before_restart")
        box.label(text="Shortcut: Cmd+Shift+R (3D View). macOS only.", icon="INFO")

        layout.separator()

        # Claude Pair
        box = layout.box()
        box.label(text="Claude Pair", icon="LINKED")
        box.prop(self, "scratch_dir")
        box.prop(self, "claude_command")
        box.prop(self, "claude_extra_args")
        box.prop(self, "claude_auto_start")
        box.prop(self, "auto_write_permissions")
        row = box.row(align=True)
        row.prop(self, "mcp_host")
        sub = box.row(align=True)
        sub.prop(self, "port_range_start")
        sub.prop(self, "port_range_end")
        box.prop(self, "start_server_on_load")
        box.prop(self, "iterm_open_as")
        box.prop(self, "iterm_profile")
        box.prop(self, "verbose_logging")
        box.label(text="Requires the official Blender MCP add-on. macOS/iTerm2 only.", icon="INFO")

        layout.separator()

        # Keymap (editable shortcuts)
        box = layout.box()
        box.label(text="Keyboard Shortcuts", icon='KEYINGSET')
        _draw_addon_keymap_items(box, context)

        layout.separator()

        # Update Section
        box = layout.box()
        box.label(text="Update Add-on", icon='FILE_REFRESH')
        box.operator(
            "preferences.addon_update_no3d",
            text="Update Add-on",
            icon='IMPORT'
        )
        box.label(text="Select the latest .zip file to install", icon='INFO')


def _draw_addon_keymap_items(layout, context):
    """Render editable keymap rows for every shortcut this addon binds.

    Uses Blender's bundled `rna_keymap_ui.draw_kmi` so the row matches the
    look-and-feel of Edit > Preferences > Keymap and supports full key
    capture / re-binding. Reads the live `_addon_keymaps` lists from each
    module rather than maintaining a parallel registry.
    """
    import rna_keymap_ui

    wm = context.window_manager
    kc = wm.keyconfigs.user
    if kc is None:
        layout.label(text="User keyconfig unavailable", icon='ERROR')
        return

    sources = (
        ("Viewport Screenshots (3D View)", viewport_screenshot._addon_keymaps),
        ("Node Screenshots (Node Editor)", node_screenshot._addon_keymaps),
        ("Clipboard / Orientation (3D View)", clipboard_paste._addon_keymaps),
    )

    for header, addon_kms in sources:
        if not addon_kms:
            continue
        col = layout.column()
        col.label(text=header, icon='DOT')
        for km, kmi in addon_kms:
            user_km = kc.keymaps.get(km.name)
            if user_km is None:
                continue
            user_kmi = user_km.keymap_items.from_id(kmi.id)
            if user_kmi is None:
                continue
            rna_keymap_ui.draw_kmi(
                ["ADDON", "USER", "DEFAULT"],
                kc, user_km, user_kmi, col, 0,
            )


def _on_wip_folder_changed(self, context):
    """When the user picks a WIP folder in the N-panel, persist it to prefs."""
    addon = context.preferences.addons.get(__name__)
    if addon and hasattr(addon, "preferences"):
        addon.preferences.export_library_path = self.no3d_wip_folder


def _default_wip_folder():
    """Seed the WM prop from addon preferences on register."""
    addon = bpy.context.preferences.addons.get(__name__)
    if addon and hasattr(addon, "preferences"):
        return addon.preferences.export_library_path or ""
    return ""


def _register_wm_props():
    bpy.types.WindowManager.no3d_extraction_method = EnumProperty(
        name="Extraction Method",
        description="Which pipeline to use when writing per-asset .blend files",
        items=EXTRACTION_METHOD_ITEMS,
        default="DATABLOCK_WRITE",
    )
    bpy.types.WindowManager.no3d_wip_folder = StringProperty(
        name="WIP Folder",
        description=(
            "Working folder where assets are auto-extracted on Mark / Save / Rename. "
            "Each asset gets its own subfolder. Saved back to addon preferences."
        ),
        subtype="DIR_PATH",
        default=_default_wip_folder(),
        update=_on_wip_folder_changed,
    )
    bpy.types.WindowManager.no3d_wip_auto_mark = BoolProperty(
        name="Auto-sync on Mark",
        description="Auto-extract a new asset to the WIP folder the moment it is marked",
        default=True,
    )
    bpy.types.WindowManager.no3d_wip_auto_save = BoolProperty(
        name="Auto-sync on Save",
        description="On every file save, re-extract assets whose source has changed",
        default=True,
    )
    bpy.types.WindowManager.no3d_wip_auto_rename = BoolProperty(
        name="Auto-sync on Rename",
        description="When an asset is renamed, rename its WIP folder to match",
        default=True,
    )
    bpy.types.WindowManager.no3d_wip_recent_count = IntProperty(
        name="Recents Shown",
        description="How many of the most recently saved assets to list",
        default=8,
        min=1,
        max=30,
    )


def _unregister_wm_props():
    for prop in (
        "no3d_extraction_method",
        "no3d_wip_folder",
        "no3d_wip_auto_mark",
        "no3d_wip_auto_save",
        "no3d_wip_auto_rename",
        "no3d_wip_recent_count",
    ):
        try:
            delattr(bpy.types.WindowManager, prop)
        except AttributeError:
            pass


def register():
    # aspect_overlay must register FIRST: NO3D_AddonPreferences holds a
    # CollectionProperty pointing at NO3D_AspectCustomPreset, which is
    # owned by aspect_overlay. Registering prefs before the PropertyGroup
    # raises "register_class(...): expected a Property derived type".
    aspect_overlay.register()
    bpy.utils.register_class(NO3D_AddonPreferences)
    _register_wm_props()
    note_manager.register()
    operators.register()
    node_screenshot.register()
    viewport_screenshot.register()
    editor_screenshot.register()
    header_screenshots.register()
    viewport_format.register()
    clipboard_paste.register()
    ui.register()
    wip.register()
    wip_sync.register()
    repo_registration.register()
    save_reload.register()
    claude_pair.register()


def unregister():
    claude_pair.unregister()
    save_reload.unregister()
    repo_registration.unregister()
    wip_sync.unregister()
    wip.unregister()
    ui.unregister()
    clipboard_paste.unregister()
    viewport_format.unregister()
    header_screenshots.unregister()
    editor_screenshot.unregister()
    viewport_screenshot.unregister()
    node_screenshot.unregister()
    operators.unregister()
    note_manager.unregister()
    _unregister_wm_props()
    bpy.utils.unregister_class(NO3D_AddonPreferences)
    # aspect_overlay last: prefs (which referenced its PropertyGroup) is
    # already gone, so its draw handlers and the WM bool can be torn
    # down cleanly.
    aspect_overlay.unregister()


if __name__ == "__main__":
    register()
