"""
Editor screenshot — capture any one Blender editor (any area, any window)
as a clean PNG, optionally with rounded transparent corners.

Built on bpy.ops.screen.screenshot_area, which natively crops to the area
rect (no chrome, no neighbours). Output is logical-pixel-sized in 5.1.

Two surfaces:
- A "Capture Editor…" operator that pops a menu of every visible area in
  every open window, with size labels.
- A direct invoke from the panel that targets the area whose token is
  passed in as a string property (so the panel dropdown selection drives it).
"""

import datetime
import logging
import os
import subprocess
import sys
import tempfile

import bpy
import numpy as np
from bpy.props import BoolProperty, IntProperty, StringProperty
from bpy.types import Operator

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Area discovery + tokens
# ---------------------------------------------------------------------------

def _area_token(window_index: int, area_index: int) -> str:
    """Stable string handle for a (window, area) pair within one panel draw."""
    return f"{window_index}:{area_index}"


def _resolve_token(token: str):
    """Return (window, area) or (None, None) if the token no longer maps."""
    try:
        wi_str, ai_str = token.split(":", 1)
        wi = int(wi_str)
        ai = int(ai_str)
    except (ValueError, AttributeError):
        return None, None
    windows = list(bpy.context.window_manager.windows)
    if wi < 0 or wi >= len(windows):
        return None, None
    win = windows[wi]
    areas = list(win.screen.areas)
    if ai < 0 or ai >= len(areas):
        return None, None
    return win, areas[ai]


def _humanize_area_type(t: str) -> str:
    return t.replace("_", " ").title().replace("3D", "3D").replace("Uv", "UV")


def list_visible_editors():
    """Walk all open Blender windows and yield
    (token, label, window_index, area_index, area_type, w, h).
    """
    for wi, win in enumerate(bpy.context.window_manager.windows):
        for ai, a in enumerate(win.screen.areas):
            yield (
                _area_token(wi, ai),
                f"{_humanize_area_type(a.type)} — {a.width}x{a.height}",
                wi, ai, a.type, a.width, a.height,
            )


# ---------------------------------------------------------------------------
# Path resolution (shared with viewport/node screenshots)
# ---------------------------------------------------------------------------

def _resolve_output_dir(context) -> str:
    addon = context.preferences.addons.get(__package__)
    pref_path = ""
    if addon and hasattr(addon, "preferences"):
        pref_path = (addon.preferences.node_screenshot_path or "").strip()
    if pref_path:
        return bpy.path.abspath(pref_path)
    blend = bpy.data.filepath
    if blend:
        return os.path.dirname(blend)
    return os.path.expanduser("~/Downloads")


def _build_filename(area_type: str) -> str:
    safe_type = area_type.lower().replace("_", "-")
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return f"editor_{safe_type}_{stamp}.png"


# ---------------------------------------------------------------------------
# Image I/O via Blender's image API
# ---------------------------------------------------------------------------

def _read_png_to_array(filepath: str) -> np.ndarray:
    """Load PNG as (H, W, 4) float32 RGBA, top-down rows."""
    img = bpy.data.images.load(filepath, check_existing=False)
    try:
        w, h = img.size
        if w <= 0 or h <= 0:
            raise RuntimeError(f"Loaded image has invalid size: {filepath}")
        channels = img.channels
        pix = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, channels)
        if channels == 3:
            alpha = np.ones((h, w, 1), dtype=np.float32)
            pix = np.concatenate([pix, alpha], axis=2)
        pix = np.flipud(pix).copy()
        return pix
    finally:
        bpy.data.images.remove(img)


def _write_array_to_png(arr: np.ndarray, filepath: str):
    h, w, _ = arr.shape
    img = bpy.data.images.new(
        name=os.path.basename(filepath),
        width=w,
        height=h,
        alpha=True,
    )
    try:
        flipped = np.flipud(arr).astype(np.float32)
        img.pixels = flipped.ravel().tolist()
        img.filepath_raw = filepath
        img.file_format = 'PNG'
        img.alpha_mode = 'STRAIGHT'
        img.save()
    finally:
        bpy.data.images.remove(img)


# ---------------------------------------------------------------------------
# Rounded corner mask
# ---------------------------------------------------------------------------

def _which_corners_outer(area, window) -> tuple:
    """Which of the four corners of `area` sit on the window's outer edge.

    Blender 5.x reserves a few pixels of gutter at top/bottom for the global
    topbar/statusbar; areas adjacent to those still belong on the rounded
    macOS window corner. Use a generous tolerance on each axis.

    Returns (tl, tr, br, bl) booleans.
    """
    tol = 32  # accommodates topbar/statusbar gutter, Blender's 1-px margin
    ax, ay, aw, ah = area.x, area.y, area.width, area.height
    ww, wh = window.width, window.height
    on_left   = ax <= tol
    on_right  = (ax + aw) >= (ww - tol)
    on_bottom = ay <= tol
    on_top    = (ay + ah) >= (wh - tol)
    return (on_top and on_left, on_top and on_right,
            on_bottom and on_right, on_bottom and on_left)


def _apply_rounded_corner_mask(arr: np.ndarray, radius: int, corners: tuple) -> np.ndarray:
    """Fade alpha to 0 outside a rounded-rect path with the given radius
    applied to the selected corners. Anti-aliased by sub-pixel distance.

    arr: (H, W, 4) float RGBA top-down
    corners: (tl, tr, br, bl) — only True corners get rounded
    """
    if radius <= 0 or not any(corners):
        return arr
    h, w = arr.shape[:2]
    radius = int(min(radius, h // 2, w // 2))
    if radius <= 0:
        return arr

    tl, tr, br, bl = corners
    out = arr.copy()
    # Build a working alpha matching arr's existing alpha (preserve interior 0s)
    alpha = out[..., 3]

    # Per-corner SDF: distance from each corner's "inner pivot" to the pixel.
    # If the pixel sits outside the radius arc (and inside the corner box),
    # alpha fades from 1 (at distance == radius) to 0 (at distance == radius+1).
    yy = np.arange(h, dtype=np.float32)[:, None]
    xx = np.arange(w, dtype=np.float32)[None, :]

    def _round_corner(mask_y, mask_x, pivot_y, pivot_x):
        # mask_y, mask_x: boolean masks for "this corner's quadrant box"
        sel = mask_y & mask_x
        if not sel.any():
            return
        dy = yy - pivot_y
        dx = xx - pivot_x
        dist = np.sqrt(dy * dy + dx * dx)
        # 1.0 inside the radius, fade to 0 over a 1-px AA band
        corner_alpha = np.clip(radius + 0.5 - dist, 0.0, 1.0)
        # Apply only inside this corner's box
        alpha[sel] = np.minimum(alpha[sel], corner_alpha[sel])

    # Pivot points are inset by `radius` from each corner.
    if tl:
        _round_corner(yy < radius, xx < radius, radius - 0.5, radius - 0.5)
    if tr:
        _round_corner(yy < radius, xx >= w - radius,
                      radius - 0.5, w - radius - 0.5)
    if br:
        _round_corner(yy >= h - radius, xx >= w - radius,
                      h - radius - 0.5, w - radius - 0.5)
    if bl:
        _round_corner(yy >= h - radius, xx < radius,
                      h - radius - 0.5, radius - 0.5)

    out[..., 3] = alpha
    return out


# ---------------------------------------------------------------------------
# Clipboard (macOS only — same path as the other screenshot operators)
# ---------------------------------------------------------------------------

def _copy_image_to_clipboard(filepath: str) -> bool:
    if sys.platform != "darwin":
        return False
    script = (
        f'set the clipboard to '
        f'(read (POSIX file "{filepath}") as «class PNGf»)'
    )
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=True, capture_output=True, timeout=5,
        )
        return True
    except Exception as exc:
        log.warning("Clipboard copy failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Capture flow
# ---------------------------------------------------------------------------

def _capture_area_to_array(window, area) -> np.ndarray:
    """Capture `area` via screen.screenshot_area and return its pixels as a
    (H, W, 4) float32 RGBA top-down array. No corner masking, no save, no
    clipboard. Pure capture step — useful when downstream needs to crop or
    composite before saving.
    """
    tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    tmp.close()
    try:
        with bpy.context.temp_override(window=window, screen=window.screen, area=area):
            bpy.ops.screen.screenshot_area(filepath=tmp.name, check_existing=False)
        if not (os.path.exists(tmp.name) and os.path.getsize(tmp.name) > 0):
            raise RuntimeError("screenshot_area wrote no file")
        return _read_png_to_array(tmp.name)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def _save_array_and_clipboard(arr: np.ndarray, out_dir: str, area_type: str):
    """Save `arr` as a PNG in `out_dir` using the editor naming scheme, then
    copy it to the clipboard. Returns (final_path, message).
    """
    os.makedirs(out_dir, exist_ok=True)
    filename = _build_filename(area_type)
    final_path = os.path.join(out_dir, filename)

    _write_array_to_png(arr, final_path)

    clip_ok = _copy_image_to_clipboard(final_path)
    if clip_ok:
        msg = f"Editor screenshot saved to {final_path} — copied to clipboard"
    else:
        msg = f"Editor screenshot saved to {final_path}"
    print(f"[no3d_asset_developer] {msg}")
    return final_path, msg


def _capture_area(window, area, out_dir, round_corners: bool, radius: int):
    """Capture `area` via screen.screenshot_area, optionally apply rounded
    corners (only on corners that touch the window's outer edge), save, and
    copy to clipboard. Returns (final_path, message).
    """
    arr = _capture_area_to_array(window, area)

    if round_corners and radius > 0:
        corners = _which_corners_outer(area, window)
        arr = _apply_rounded_corner_mask(arr, radius, corners)

    return _save_array_and_clipboard(arr, out_dir, area.type)


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

def _read_capture_prefs(context):
    """Pull (round_corners, radius) from prefs with safe fallbacks."""
    addon = context.preferences.addons.get(__package__)
    if addon and hasattr(addon, "preferences"):
        prefs = addon.preferences
        return (
            bool(getattr(prefs, "editor_capture_round_corners", True)),
            int(getattr(prefs, "editor_capture_corner_radius", 10)),
        )
    return True, 10


class NO3D_OT_editor_screenshot(Operator):
    """Screenshot a chosen editor area — clean rectangle, optional rounded corners."""
    bl_idname = "no3d.editor_screenshot"
    bl_label = "Capture Editor"
    bl_description = (
        "Capture a single editor area as a PNG (no chrome, no neighbours). "
        "Optionally rounds the corners that touch the window's outer edge"
    )
    bl_options = {'REGISTER'}

    area_token: StringProperty(
        name="Area Token",
        description="window:area index — set by the panel dropdown",
        default="",
    )

    def execute(self, context):
        if not self.area_token:
            self.report({'ERROR'}, "No editor selected")
            return {'CANCELLED'}

        win, area = _resolve_token(self.area_token)
        if win is None or area is None:
            self.report({'ERROR'}, "Selected editor no longer exists — refresh the dropdown")
            return {'CANCELLED'}

        round_corners, radius = _read_capture_prefs(context)
        out_dir = _resolve_output_dir(context)
        try:
            path, msg = _capture_area(win, area, out_dir, round_corners, radius)
        except Exception as exc:
            log.exception("Editor screenshot failed")
            self.report({'ERROR'}, f"Capture failed: {exc}")
            return {'CANCELLED'}

        self.report({'INFO'}, msg)
        return {'FINISHED'}


class NO3D_OT_editor_screenshot_picker(Operator):
    """Pop a menu listing every visible editor and capture the chosen one."""
    bl_idname = "no3d.editor_screenshot_picker"
    bl_label = "Capture Editor…"
    bl_description = "Pick an editor from a menu, then capture it"
    bl_options = {'REGISTER'}

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self, width=320)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Pick an editor to capture:")
        for token, label, _, _, _, _, _ in list_visible_editors():
            op = layout.operator(
                "no3d.editor_screenshot",
                text=label,
            )
            op.area_token = token

    def execute(self, context):
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_classes = (
    NO3D_OT_editor_screenshot,
    NO3D_OT_editor_screenshot_picker,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
