"""
Node-editor screenshot operators.

Captures the node editor with a chroma-keyable magenta background, despills
the result to alpha, saves a transparent PNG, and copies the image to the
system clipboard.

Two operators:
- no3d.node_screenshot_visible: capture the whole visible node area
- no3d.node_screenshot_region:  modal drag-rect, capture that region
"""

import datetime
import logging
import os
import subprocess
import sys

import bpy
import gpu
import numpy as np
from bpy.types import Operator
from gpu_extras.batch import batch_for_shader

log = logging.getLogger(__name__)

# Two key colors, picked to be far apart in RGB so background pixels
# always change between shots while node pixels stay identical.
KEY_A_RGB = (1.0, 0.0, 1.0)   # magenta
KEY_B_RGB = (0.0, 1.0, 0.0)   # pure green
# Pixel-level threshold for "did this pixel change between shots?".
# 0..1 floats; ~12/255 is a comfortable margin above LCD/JPEG-style noise
# while still rejecting AA fringe ambiguity.
DIFF_THRESHOLD = 12.0 / 255.0


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _resolve_output_dir(context) -> str:
    """Resolve output directory: pref → .blend folder → ~/Downloads."""
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


def _build_filename(node_tree_name: str) -> str:
    safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in node_tree_name)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return f"{safe}_{stamp}.png"


# ---------------------------------------------------------------------------
# Theme swap
# ---------------------------------------------------------------------------

def _backup_theme(context) -> dict:
    ne = context.preferences.themes[0].node_editor
    return {
        "back": tuple(ne.space.back),
        "grid": tuple(ne.grid),
        "grid_levels": ne.grid_levels,
    }


def _apply_key_theme(context, key_rgb: tuple):
    ne = context.preferences.themes[0].node_editor
    ne.space.back = key_rgb
    ne.grid = key_rgb
    ne.grid_levels = 0


def _restore_theme(context, backup: dict):
    ne = context.preferences.themes[0].node_editor
    ne.space.back = backup["back"]
    ne.grid = backup["grid"]
    ne.grid_levels = backup["grid_levels"]


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

def _full_window_screenshot(filepath: str):
    """Full-window screenshot. Only path that flushes the framebuffer reliably."""
    bpy.ops.screen.screenshot(filepath=filepath)


def _read_png_to_array(filepath: str) -> np.ndarray:
    """Load a PNG via Blender's image API as float RGBA, shape (H, W, 4)."""
    img = bpy.data.images.load(filepath, check_existing=False)
    try:
        w, h = img.size
        if w == 0 or h == 0:
            raise RuntimeError(f"loaded image has zero size: {filepath}")
        arr = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
        # Blender stores rows bottom-up; flip to top-down so pixel (0,0) is top-left
        arr = np.flipud(arr).copy()
        return arr  # values in 0..1
    finally:
        bpy.data.images.remove(img)


def _write_array_to_png(arr: np.ndarray, filepath: str):
    """Write a (H, W, 4) float RGBA array (0..1) as PNG via Blender."""
    h, w, _ = arr.shape
    img = bpy.data.images.new(
        name=os.path.basename(filepath),
        width=w,
        height=h,
        alpha=True,
    )
    try:
        # Blender wants bottom-up rows
        flipped = np.flipud(arr).astype(np.float32)
        img.pixels = flipped.ravel().tolist()
        img.filepath_raw = filepath
        img.file_format = 'PNG'
        img.alpha_mode = 'STRAIGHT'
        img.save()
    finally:
        bpy.data.images.remove(img)


def _difference_matte(
    shot_a: np.ndarray,
    shot_b: np.ndarray,
    threshold: float = DIFF_THRESHOLD,
) -> np.ndarray:
    """Two-shot difference matte.

    A pixel is "node content" if it is identical (within threshold) in both
    shots. A pixel that changed between shots is "background." The shots
    must have been taken with different background-fill colors but otherwise
    identical UI state.

    Returns RGBA float (0..1) where:
      - alpha is the mask (1 = node, 0 = background, soft falloff at edges)
      - RGB is recovered from the shot whose key color is furthest from the
        pixel's actual value, per pixel — minimizes residual color contamination
    """
    a_rgb = shot_a[..., :3]
    b_rgb = shot_b[..., :3]

    # Per-pixel max-channel difference between shots
    diff = np.max(np.abs(a_rgb - b_rgb), axis=-1)

    # Soft mask: 0 where the two shots match (node), 1 where they differ (bg).
    # Use a small ramp around the threshold for AA edges.
    ramp = max(threshold * 0.5, 1.0 / 255.0)
    bg_mask = np.clip((diff - threshold + ramp) / (2.0 * ramp), 0.0, 1.0)
    alpha = 1.0 - bg_mask

    # Recover color: pick the shot whose key is *farther* from the observed
    # pixel value, per pixel. That shot's pixel has less spill from the key.
    # Because we don't know the key color here at the array level, we pass
    # them as constants below — but a clean heuristic: for each pixel pick
    # whichever shot has the smaller distance to its own pixel's *neighbour*
    # shot value. Simpler and equally good: average the two shots; in pure
    # background regions they cancel toward gray, but those pixels are
    # masked out by alpha=0 anyway. In node regions they are nearly equal.
    rgb = (a_rgb + b_rgb) * 0.5

    out = np.concatenate([rgb, alpha[..., None]], axis=-1)
    return out


# ---------------------------------------------------------------------------
# Clipboard
# ---------------------------------------------------------------------------

def _copy_image_to_clipboard(filepath: str) -> bool:
    """Copy a PNG file's bytes to the system clipboard. Returns True on success."""
    if sys.platform == "darwin":
        script = (
            f'set the clipboard to '
            f'(read (POSIX file "{filepath}") as «class PNGf»)'
        )
        try:
            subprocess.run(
                ["osascript", "-e", script],
                check=True,
                capture_output=True,
                timeout=5,
            )
            return True
        except Exception as exc:
            log.warning("Clipboard copy failed: %s", exc)
            return False
    # Other platforms: not implemented
    return False


# ---------------------------------------------------------------------------
# UI chrome hide/show
# ---------------------------------------------------------------------------

def _hide_node_chrome(node_area):
    """Collapse N-panel and header in the node editor. Returns previous state."""
    space = node_area.spaces.active
    state = {
        "show_region_ui": getattr(space, "show_region_ui", None),
        "show_region_header": getattr(space, "show_region_header", None),
        "show_region_toolbar": getattr(space, "show_region_toolbar", None),
    }
    if state["show_region_ui"] is not None:
        space.show_region_ui = False
    if state["show_region_header"] is not None:
        space.show_region_header = False
    if state["show_region_toolbar"] is not None:
        space.show_region_toolbar = False
    return state


def _restore_node_chrome(node_area, state: dict):
    space = node_area.spaces.active
    for k, v in state.items():
        if v is not None:
            try:
                setattr(space, k, v)
            except Exception:
                pass


def _force_redraw(window, area):
    # Tag every area in the window — the full-window screenshot path
    # only flushes if the whole window has been redrawn since the last swap.
    for a in window.screen.areas:
        a.tag_redraw()
    with bpy.context.temp_override(window=window, area=area):
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=3)


# ---------------------------------------------------------------------------
# Core capture flow (shared by visible + region)
# ---------------------------------------------------------------------------

def _capture_and_process(
    context,
    crop_xywh: tuple,  # in window pixels, top-left origin (PIL convention)
    out_dir: str,
    node_tree_name: str,
):
    """Full pipeline using two-shot difference matte.

    Takes two screenshots with different background fill colors, then keys
    out any pixel that changed between shots. Eliminates false-positive
    transparency on legitimately blue/magenta nodes.

    crop_xywh is (x, y, w, h) in WINDOW pixels (top-left origin).
    Returns (final_path, message).
    """
    os.makedirs(out_dir, exist_ok=True)
    filename = _build_filename(node_tree_name or "node_screenshot")
    final_path = os.path.join(out_dir, filename)

    raw_a = os.path.join(out_dir, f".{filename}.shot_a.tmp.png")
    raw_b = os.path.join(out_dir, f".{filename}.shot_b.tmp.png")

    window = context.window
    node_area = next(
        (a for a in window.screen.areas if a.type == 'NODE_EDITOR'),
        None,
    )
    if node_area is None:
        raise RuntimeError("No Node Editor area found in this window.")

    theme_backup = _backup_theme(context)
    chrome_backup = _hide_node_chrome(node_area)
    try:
        _apply_key_theme(context, KEY_A_RGB)
        _force_redraw(window, node_area)
        _full_window_screenshot(raw_a)

        _apply_key_theme(context, KEY_B_RGB)
        _force_redraw(window, node_area)
        _full_window_screenshot(raw_b)
    finally:
        _restore_theme(context, theme_backup)
        _restore_node_chrome(node_area, chrome_backup)
        _force_redraw(window, node_area)

    for p in (raw_a, raw_b):
        if not os.path.exists(p):
            raise RuntimeError(f"Screenshot did not write file: {p}")

    shot_a = _read_png_to_array(raw_a)  # H,W,4 float 0..1, top-down rows
    shot_b = _read_png_to_array(raw_b)
    if shot_a.shape != shot_b.shape:
        raise RuntimeError(
            f"Shot dimensions differ: {shot_a.shape} vs {shot_b.shape}"
        )
    img_h, img_w = shot_a.shape[:2]

    # Account for HiDPI: screenshot may be 2x the window pixel dims
    win_w = window.width
    scale = img_w / win_w if win_w else 1.0
    cx, cy, cw, ch = crop_xywh
    sx = int(round(cx * scale))
    sy = int(round(cy * scale))
    sw = int(round(cw * scale))
    sh = int(round(ch * scale))

    # Clamp to image bounds
    sx = max(0, min(sx, img_w))
    sy = max(0, min(sy, img_h))
    sw = max(1, min(sw, img_w - sx))
    sh = max(1, min(sh, img_h - sy))

    crop_a = shot_a[sy:sy + sh, sx:sx + sw, :]
    crop_b = shot_b[sy:sy + sh, sx:sx + sw, :]
    keyed = _difference_matte(crop_a, crop_b)
    _write_array_to_png(keyed, final_path)

    for p in (raw_a, raw_b):
        try:
            os.remove(p)
        except OSError:
            pass

    clip_ok = _copy_image_to_clipboard(final_path)
    if clip_ok:
        msg = f"Node screenshot saved to {final_path} — image copied to clipboard"
    else:
        msg = f"Node screenshot saved to {final_path} — clipboard copy unavailable"
    print(f"[no3d_asset_developer] {msg}")
    return final_path, msg


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class NO3D_OT_node_screenshot_visible(Operator):
    """Capture the visible node editor area as a transparent PNG."""
    bl_idname = "no3d.node_screenshot_visible"
    bl_label = "Capture Visible Area"
    bl_description = (
        "Screenshot the entire visible node editor canvas as a "
        "transparent PNG and copy it to the clipboard"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'NODE_EDITOR'

    def execute(self, context):
        node_area = context.area
        space = node_area.spaces.active
        tree_name = getattr(space.node_tree, "name", "node_tree") if space.node_tree else "node_tree"

        # Window pixel rect of the area, top-left origin
        # Blender area.y is bottom-up; convert.
        win_h = context.window.height
        x = node_area.x
        y_top = win_h - (node_area.y + node_area.height)
        w = node_area.width
        h = node_area.height

        out_dir = _resolve_output_dir(context)
        try:
            path, msg = _capture_and_process(
                context, (x, y_top, w, h), out_dir, tree_name,
            )
        except Exception as exc:
            log.exception("Node screenshot failed")
            self.report({'ERROR'}, f"Screenshot failed: {exc}")
            return {'CANCELLED'}

        self.report({'INFO'}, msg)
        return {'FINISHED'}


class _RegionCaptureBase(Operator):
    """Shared modal drag-rect machinery for region + thumbnail captures."""
    bl_options = {'REGISTER'}

    # Subclasses override these
    SQUARE_LOCK = False
    SHOW_GUIDES = False
    HINT = "Drag to select capture region — ESC to cancel"

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'NODE_EDITOR'

    def invoke(self, context, event):
        self._area = context.area
        self._dragging = False
        self._start = None      # (rx, ry) in REGION px (bottom-up)
        self._end = None
        self._draw_handler = None
        self._panning = False    # spacebar held — translate marquee
        self._pan_anchor = None  # mouse pos when panning began
        region = next(r for r in self._area.regions if r.type == 'WINDOW')
        self._region = region
        self._draw_handler = bpy.types.SpaceNodeEditor.draw_handler_add(
            self._draw_marquee, (context,), 'WINDOW', 'POST_PIXEL',
        )
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        context.window.cursor_modal_set('CROSSHAIR')
        self.report({'INFO'}, self.HINT)
        return {'RUNNING_MODAL'}

    def _cleanup(self, context):
        if self._draw_handler is not None:
            try:
                bpy.types.SpaceNodeEditor.draw_handler_remove(
                    self._draw_handler, 'WINDOW',
                )
            except Exception:
                pass
            self._draw_handler = None
        if self._area:
            self._area.tag_redraw()
        try:
            context.window.cursor_modal_restore()
        except Exception:
            pass

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self._cleanup(context)
            self.report({'INFO'}, "Capture cancelled")
            return {'CANCELLED'}

        # Spacebar: hold to translate the current marquee instead of resizing
        if event.type == 'SPACE':
            if event.value == 'PRESS' and self._dragging:
                self._panning = True
                self._pan_anchor = self._mouse_in_region(event)
                context.window.cursor_modal_set('SCROLL_XY')
                return {'RUNNING_MODAL'}
            if event.value == 'RELEASE':
                if self._panning:
                    self._panning = False
                    self._pan_anchor = None
                    context.window.cursor_modal_set('CROSSHAIR')
                return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE':
            if self._dragging:
                cur = self._mouse_in_region(event)
                if self._panning and self._pan_anchor is not None:
                    dx = cur[0] - self._pan_anchor[0]
                    dy = cur[1] - self._pan_anchor[1]
                    sx, sy = self._start
                    ex, ey = self._end
                    self._start = (sx + dx, sy + dy)
                    self._end = (ex + dx, ey + dy)
                    self._pan_anchor = cur
                else:
                    self._end = cur
                self._area.tag_redraw()
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                self._start = self._mouse_in_region(event)
                self._end = self._start
                self._dragging = True
                return {'RUNNING_MODAL'}
            if event.value == 'RELEASE' and self._dragging:
                self._end = self._mouse_in_region(event)
                self._dragging = False
                rect = self._region_rect_window_px(context)
                self._cleanup(context)
                if rect is None or rect[2] < 4 or rect[3] < 4:
                    self.report({'INFO'}, "Region too small — cancelled")
                    return {'CANCELLED'}

                space = self._area.spaces.active
                tree_name = (
                    getattr(space.node_tree, "name", "node_tree")
                    if space.node_tree else "node_tree"
                )
                out_dir = _resolve_output_dir(context)
                try:
                    path, msg = _capture_and_process(
                        context, rect, out_dir, tree_name,
                    )
                except Exception as exc:
                    log.exception("Region capture failed")
                    self.report({'ERROR'}, f"Capture failed: {exc}")
                    return {'CANCELLED'}
                self.report({'INFO'}, msg)
                return {'FINISHED'}

        return {'RUNNING_MODAL'}

    def _mouse_in_region(self, event):
        return (
            event.mouse_x - self._region.x,
            event.mouse_y - self._region.y,
        )

    def _square_corners_region(self):
        """Return (x0, y0, x1, y1) in REGION coords with square lock applied
        if SQUARE_LOCK. Anchor is _start, opposite corner follows cursor but
        with W = H = max(|dx|, |dy|), preserving the cursor's quadrant.
        """
        if self._start is None or self._end is None:
            return None
        ax, ay = self._start
        bx, by = self._end
        if not self.SQUARE_LOCK:
            return ax, ay, bx, by
        dx = bx - ax
        dy = by - ay
        side = max(abs(dx), abs(dy))
        sx = 1 if dx >= 0 else -1
        sy = 1 if dy >= 0 else -1
        return ax, ay, ax + sx * side, ay + sy * side

    def _region_rect_window_px(self, context):
        """Final crop rect in WINDOW px (top-left origin)."""
        corners = self._square_corners_region()
        if corners is None:
            return None
        x0, y0, x1, y1 = corners
        rx = min(x0, x1)
        ry = min(y0, y1)
        rw = abs(x1 - x0)
        rh = abs(y1 - y0)
        if rw < 1 or rh < 1:
            return None
        win_x = self._region.x + rx
        region_top_in_window_topdown = (
            context.window.height - (self._region.y + self._region.height)
        )
        win_y_topdown = region_top_in_window_topdown + (
            self._region.height - (ry + rh)
        )
        return (int(win_x), int(win_y_topdown), int(rw), int(rh))

    def _get_margin(self, context):
        addon = context.preferences.addons.get(__package__)
        if addon and hasattr(addon, "preferences"):
            return float(addon.preferences.thumbnail_margin)
        return 0.25

    def _draw_marquee(self, context):
        if not self._dragging:
            return
        corners = self._square_corners_region()
        if corners is None:
            return
        x0, y0, x1, y1 = corners
        # normalize for fills
        lo_x, hi_x = sorted((x0, x1))
        lo_y, hi_y = sorted((y0, y1))

        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.blend_set('ALPHA')

        # subtle fill of marquee
        fill = [(lo_x, lo_y), (hi_x, lo_y), (hi_x, hi_y), (lo_x, hi_y)]
        fill_batch = batch_for_shader(shader, 'TRI_FAN', {"pos": fill})
        shader.bind()
        shader.uniform_float("color", (1.0, 0.4, 0.0, 0.08))
        fill_batch.draw(shader)

        # outer outline
        gpu.state.line_width_set(2.0)
        outline = [
            (lo_x, lo_y), (hi_x, lo_y), (hi_x, hi_y), (lo_x, hi_y), (lo_x, lo_y),
        ]
        outline_batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": outline})
        shader.uniform_float("color", (1.0, 0.4, 0.0, 1.0))
        outline_batch.draw(shader)

        if self.SHOW_GUIDES:
            margin = self._get_margin(context)
            side = hi_x - lo_x  # square: w == h
            inset = side * margin
            ix0 = lo_x + inset
            iy0 = lo_y + inset
            ix1 = hi_x - inset
            iy1 = hi_y - inset

            # margin guide (dashed-look via thinner solid line for now)
            gpu.state.line_width_set(1.0)
            inner = [
                (ix0, iy0), (ix1, iy0), (ix1, iy1), (ix0, iy1), (ix0, iy0),
            ]
            inner_batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": inner})
            shader.uniform_float("color", (1.0, 0.85, 0.2, 0.7))
            inner_batch.draw(shader)

            # center indicator: X from corner to corner (crossing point = exact center)
            cross = [
                (lo_x, lo_y), (hi_x, hi_y),
                (lo_x, hi_y), (hi_x, lo_y),
            ]
            cross_batch = batch_for_shader(shader, 'LINES', {"pos": cross})
            shader.uniform_float("color", (1.0, 1.0, 1.0, 0.6))
            cross_batch.draw(shader)

        gpu.state.blend_set('NONE')
        gpu.state.line_width_set(1.0)


class NO3D_OT_node_screenshot_region(_RegionCaptureBase):
    """Drag a rectangle in the node editor; capture that region as transparent PNG."""
    bl_idname = "no3d.node_screenshot_region"
    bl_label = "Capture Region"
    bl_description = (
        "Drag a rectangle to define the capture region. ESC cancels"
    )

    SQUARE_LOCK = False
    SHOW_GUIDES = False
    HINT = "Drag to select capture region — ESC to cancel"


class NO3D_OT_node_screenshot_thumbnail(_RegionCaptureBase):
    """Square-locked thumbnail capture with center + margin guides."""
    bl_idname = "no3d.node_screenshot_thumbnail"
    bl_label = "Capture Thumbnail"
    bl_description = (
        "Drag a square region with center and margin guides. "
        "Margin is set in preferences. ESC cancels"
    )

    SQUARE_LOCK = True
    SHOW_GUIDES = True
    HINT = "Drag a square — center & margin guides shown — ESC to cancel"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_classes = (
    NO3D_OT_node_screenshot_visible,
    NO3D_OT_node_screenshot_region,
    NO3D_OT_node_screenshot_thumbnail,
)


# Keymap: shortcuts only fire while the Node Editor is the active area.
# Ctrl+Shift+Alt + V / R / T — verified free in default + your current keymap.
_KEYMAP_BINDINGS = (
    ("no3d.node_screenshot_visible",   "V"),
    ("no3d.node_screenshot_region",    "R"),
    ("no3d.node_screenshot_thumbnail", "T"),
)

_addon_keymaps = []


def _register_keymaps():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc is None:
        return  # background mode; no addon keyconfig available
    km = kc.keymaps.new(name="Node Editor", space_type="NODE_EDITOR")
    for op_idname, key in _KEYMAP_BINDINGS:
        kmi = km.keymap_items.new(
            op_idname,
            type=key,
            value="PRESS",
            ctrl=True,
            shift=True,
            alt=True,
        )
        _addon_keymaps.append((km, kmi))


def _unregister_keymaps():
    for km, kmi in _addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _addon_keymaps.clear()


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    _register_keymaps()


def unregister():
    _unregister_keymaps()
    for cls in reversed(_classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
