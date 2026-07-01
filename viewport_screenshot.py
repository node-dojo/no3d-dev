"""
3D Viewport screenshot operators.

Six selectable capture methods (see preferences). Three operators dispatch
on the chosen method and return RGBA arrays which are then cropped to the
user's marquee/region.

- no3d.viewport_screenshot_visible: capture the whole visible 3D area
- no3d.viewport_screenshot_region:  modal drag-rect, capture that region
- no3d.viewport_screenshot_thumbnail: square-locked drag, with center+margin guides
"""

import datetime
import logging
import os
import subprocess
import sys
import tempfile

import bpy
import gpu
import numpy as np
from bpy.types import Operator
from gpu_extras.batch import batch_for_shader

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path resolution (same as node_screenshot, but lives here for clarity)
# ---------------------------------------------------------------------------

def _resolve_output_dir(context) -> str:
    addon = context.preferences.addons.get(__package__)
    pref_path = ""
    if addon and hasattr(addon, "preferences"):
        # Reuse the same pref as node screenshots — single output folder concept
        pref_path = (addon.preferences.node_screenshot_path or "").strip()
    if pref_path:
        return bpy.path.abspath(pref_path)
    blend = bpy.data.filepath
    if blend:
        return os.path.dirname(blend)
    return os.path.expanduser("~/Downloads")


def _build_filename(prefix: str = "viewport", method_tag: str = "") -> str:
    safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in prefix)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    if method_tag:
        return f"{safe}_{method_tag}_{stamp}.png"
    return f"{safe}_{stamp}.png"


# ---------------------------------------------------------------------------
# Overlay/gizmo hide & restore
# ---------------------------------------------------------------------------

def _hide_viewport_chrome(space, keep_gizmos: bool = False):
    """Disable overlay sub-features individually rather than toggling
    show_overlays at the top level — that master toggle short-circuits
    the offscreen render entirely on Blender 5.x. We disable each
    overlay element so the render is geometry-only.

    If keep_gizmos is True, gizmos stay visible in the capture.
    """
    overlay = getattr(space, "overlay", None)
    state = {"show_gizmo": getattr(space, "show_gizmo", None)}

    if hasattr(space, "show_gizmo") and not keep_gizmos:
        space.show_gizmo = False

    if overlay is not None:
        # Snapshot every overlay sub-toggle we touch so restore is exact
        keys = (
            "show_floor",
            "show_axis_x", "show_axis_y", "show_axis_z",
            "show_ortho_grid",
            "show_relationship_lines",
            "show_cursor",
            "show_extras",
            "show_bones",
            "show_motion_paths",
            "show_object_origins",
            "show_object_origins_all",
            "show_outline_selected",
            "show_text",
            "show_stats",
            "show_annotation",
            "show_face_orientation",
            "show_wireframes",
        )
        for k in keys:
            if hasattr(overlay, k):
                state[k] = getattr(overlay, k)
                try:
                    setattr(overlay, k, False)
                except Exception:
                    pass
    return state


def _restore_viewport_chrome(space, state):
    if state.get("show_gizmo") is not None and hasattr(space, "show_gizmo"):
        space.show_gizmo = state["show_gizmo"]
    overlay = getattr(space, "overlay", None)
    if overlay is None:
        return
    for k, v in state.items():
        if k == "show_gizmo":
            continue
        if hasattr(overlay, k):
            try:
                setattr(overlay, k, v)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Offscreen render — the heart of the no-keying approach
# ---------------------------------------------------------------------------

def _offscreen_render_viewport(
    context,
    area,
    region,
    width: int,
    height: int,
    shading_override: str = None,  # None | 'SOLID' | 'SOLID_FLAT_WHITE'
) -> np.ndarray:
    """Render the 3D viewport to an offscreen framebuffer with transparent
    background and return an (H, W, 4) float RGBA array (top-down rows).

    shading_override:
      None: leave space.shading.type as-is.
      'SOLID': force Solid shading for the duration.
      'SOLID_FLAT_WHITE': Solid + single flat-white color + flat lighting (mask pass).
    """
    space = area.spaces.active
    rv3d = space.region_3d
    if rv3d is None:
        raise RuntimeError("Viewport has no region_3d state")

    shading = getattr(space, "shading", None)
    shading_backup = {}
    if shading_override and shading is not None:
        for attr in ("type", "color_type", "single_color", "light", "background_type"):
            if hasattr(shading, attr):
                shading_backup[attr] = getattr(shading, attr)
        try:
            shading.type = 'SOLID'
        except Exception:
            pass
        if shading_override == 'SOLID_FLAT_WHITE':
            for attr, val in (
                ("color_type", 'SINGLE'),
                ("single_color", (1.0, 1.0, 1.0)),
                ("light", 'FLAT'),
            ):
                if hasattr(shading, attr):
                    try:
                        setattr(shading, attr, val)
                    except Exception:
                        pass

    view_matrix = rv3d.view_matrix.copy()
    proj_matrix = rv3d.window_matrix.copy()

    try:
        offscreen = gpu.types.GPUOffScreen(width, height)
        try:
            offscreen.draw_view3d(
                scene=context.scene,
                view_layer=context.view_layer,
                view3d=space,
                region=region,
                view_matrix=view_matrix,
                projection_matrix=proj_matrix,
                do_color_management=True,
                draw_background=False,  # leaves alpha=0 outside geometry
            )
            offscreen.bind()
            try:
                fb = gpu.state.active_framebuffer_get()
                buf = fb.read_color(
                    0, 0, width, height, 4, 0, 'FLOAT',
                )
            finally:
                offscreen.unbind()
        finally:
            offscreen.free()
    finally:
        if shading_override and shading is not None:
            for attr, val in shading_backup.items():
                try:
                    setattr(shading, attr, val)
                except Exception:
                    pass

    arr = np.asarray(buf.to_list(), dtype=np.float32).reshape(height, width, 4)
    # GPU framebuffer is bottom-up; flip to top-down
    arr = np.flipud(arr).copy()
    np.clip(arr, 0.0, 1.0, out=arr)
    return arr


# ---------------------------------------------------------------------------
# Helpers shared by screen-capture methods
# ---------------------------------------------------------------------------

def _read_image_pixels_topdown(filepath: str) -> np.ndarray:
    """Load a PNG via Blender's image API and return (H, W, 4) float32 top-down RGBA."""
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
        # Blender pixels are bottom-up
        pix = np.flipud(pix).copy()
        return pix
    finally:
        bpy.data.images.remove(img)


def _screen_capture_to_array(context, area, region) -> np.ndarray:
    """Run bpy.ops.screen.screenshot, crop to viewport region, return RGBA.

    Handles HiDPI: bpy.ops.screen.screenshot may write physical pixels (2x logical
    on Retina). Detect by comparing image dimensions to window logical size.
    """
    tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    tmp.close()
    try:
        bpy.ops.screen.screenshot(filepath=tmp.name)
        full = _read_image_pixels_topdown(tmp.name)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    win = context.window
    img_h, img_w = full.shape[:2]
    scale_x = img_w / max(1, win.width)
    scale_y = img_h / max(1, win.height)

    # Region origin in window pixels (logical), then scaled to image space.
    # area.x/region.x are window-relative logical px; window y is bottom-up.
    rx = int(region.x * scale_x)
    rw = int(region.width * scale_x)
    rh = int(region.height * scale_y)
    # window-bottom-up region y → image-top-down image y
    ry_bu = int(region.y * scale_y)
    ry_td = img_h - (ry_bu + rh)

    # Clamp
    rx = max(0, min(rx, img_w))
    ry_td = max(0, min(ry_td, img_h))
    rw = max(1, min(rw, img_w - rx))
    rh = max(1, min(rh, img_h - ry_td))

    return full[ry_td:ry_td + rh, rx:rx + rw, :].copy()


def _resample_nearest(arr: np.ndarray, target_h: int, target_w: int) -> np.ndarray:
    """Numpy-only nearest-neighbor resample of an (H, W, C) array."""
    src_h, src_w = arr.shape[:2]
    if src_h == target_h and src_w == target_w:
        return arr
    yi = (np.arange(target_h) * (src_h / target_h)).astype(np.int32)
    xi = (np.arange(target_w) * (src_w / target_w)).astype(np.int32)
    yi = np.clip(yi, 0, src_h - 1)
    xi = np.clip(xi, 0, src_w - 1)
    return arr[yi[:, None], xi[None, :], :].copy()


# ---------------------------------------------------------------------------
# Method implementations — each returns (H, W, 4) float32 RGBA top-down
# ---------------------------------------------------------------------------

def _capture_offscreen_solid(context, area, region, multiplier, keep_gizmos):
    space = area.spaces.active
    chrome = _hide_viewport_chrome(space, keep_gizmos=keep_gizmos)
    try:
        w = region.width * multiplier
        h = region.height * multiplier
        return _offscreen_render_viewport(
            context, area, region, w, h, shading_override='SOLID',
        )
    finally:
        _restore_viewport_chrome(space, chrome)
        area.tag_redraw()


def _capture_offscreen_material(context, area, region, multiplier, keep_gizmos):
    space = area.spaces.active
    chrome = _hide_viewport_chrome(space, keep_gizmos=keep_gizmos)
    try:
        w = region.width * multiplier
        h = region.height * multiplier
        return _offscreen_render_viewport(
            context, area, region, w, h, shading_override=None,
        )
    finally:
        _restore_viewport_chrome(space, chrome)
        area.tag_redraw()


def _capture_screen_capture(context, area, region, multiplier, keep_gizmos):
    # Multiplier ignored — native HiDPI only.
    return _screen_capture_to_array(context, area, region)


def _capture_cryptomatte_offscreen_mask(context, area, region, multiplier, keep_gizmos):
    space = area.spaces.active
    # Pass A: flat-white solid mask at multiplier resolution
    chrome = _hide_viewport_chrome(space, keep_gizmos=False)
    try:
        mw = region.width * multiplier
        mh = region.height * multiplier
        mask_arr = _offscreen_render_viewport(
            context, area, region, mw, mh, shading_override='SOLID_FLAT_WHITE',
        )
    finally:
        _restore_viewport_chrome(space, chrome)
        area.tag_redraw()

    # Pass B: full screen capture for RGB
    rgb_arr = _screen_capture_to_array(context, area, region)

    # Composite: align resolutions (resample mask to RGB shape)
    rh, rw = rgb_arr.shape[:2]
    mask_resized = _resample_nearest(mask_arr, rh, rw)
    alpha = mask_resized[:, :, 3:4]
    out = rgb_arr.copy()
    out[:, :, 3:4] = alpha
    np.clip(out, 0.0, 1.0, out=out)
    return out


def _capture_render_opengl(context, area, region, multiplier, keep_gizmos):
    """bpy.ops.render.opengl(view_context=True) at multiplier resolution.
    Save+restore render settings since opengl-render in Solid mode writes RGB only.
    """
    scene = context.scene
    rnd = scene.render
    image_settings = rnd.image_settings

    backup = {
        "resolution_x": rnd.resolution_x,
        "resolution_y": rnd.resolution_y,
        "resolution_percentage": rnd.resolution_percentage,
        "file_format": image_settings.file_format,
        "color_mode": image_settings.color_mode,
        "film_transparent": getattr(rnd, "film_transparent", False),
    }

    space = area.spaces.active
    chrome = _hide_viewport_chrome(space, keep_gizmos=keep_gizmos)

    tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    tmp.close()
    try:
        rnd.resolution_x = region.width * multiplier
        rnd.resolution_y = region.height * multiplier
        rnd.resolution_percentage = 100
        image_settings.file_format = 'PNG'
        image_settings.color_mode = 'RGBA'
        # Force transparent film so the OpenGL render produces a real alpha
        # channel regardless of the user's current scene setting. Restored
        # in the finally block from `backup`.
        if hasattr(rnd, "film_transparent"):
            rnd.film_transparent = True

        # Override context so the operator targets THIS area/region
        with context.temp_override(area=area, region=region, space_data=space):
            bpy.ops.render.opengl(view_context=True, write_still=False)

        render_img = bpy.data.images.get('Render Result')
        if render_img is None:
            raise RuntimeError("No 'Render Result' image after opengl render")
        render_img.save_render(filepath=tmp.name, scene=scene)
        arr = _read_image_pixels_topdown(tmp.name)
        return arr
    finally:
        _restore_viewport_chrome(space, chrome)
        area.tag_redraw()
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        rnd.resolution_x = backup["resolution_x"]
        rnd.resolution_y = backup["resolution_y"]
        rnd.resolution_percentage = backup["resolution_percentage"]
        image_settings.file_format = backup["file_format"]
        image_settings.color_mode = backup["color_mode"]
        if hasattr(rnd, "film_transparent"):
            rnd.film_transparent = backup["film_transparent"]


def _find_world_solid_color_socket(world):
    """Locate an input socket whose name contains 'solid color' (case-insensitive)
    on the world's surface output's source group. Returns the socket or None.
    """
    if world is None or not getattr(world, "use_nodes", False) or world.node_tree is None:
        return None
    for node in world.node_tree.nodes:
        for sock in getattr(node, "inputs", []):
            name = (sock.name or "").lower()
            if "solid color" in name:
                return sock
    return None


def _capture_world_swap_diff(context, area, region, multiplier, keep_gizmos):
    """Magenta/green world swap, difference matte → alpha. Multiplier ignored."""
    world = context.scene.world
    socket = _find_world_solid_color_socket(world)
    if socket is None:
        log.warning("World has no 'Solid Color' input — falling back to OFFSCREEN_SOLID")
        return _capture_offscreen_solid(context, area, region, multiplier, keep_gizmos)

    backup = None
    try:
        backup = tuple(socket.default_value)
    except Exception:
        backup = None

    try:
        # Magenta pass
        try:
            socket.default_value = (1.0, 0.0, 1.0, 1.0)
        except Exception:
            socket.default_value = (1.0, 0.0, 1.0)
        _force_redraw(area)
        magenta = _screen_capture_to_array(context, area, region)

        # Green pass
        try:
            socket.default_value = (0.0, 1.0, 0.0, 1.0)
        except Exception:
            socket.default_value = (0.0, 1.0, 0.0)
        _force_redraw(area)
        green = _screen_capture_to_array(context, area, region)
    finally:
        if backup is not None:
            try:
                socket.default_value = backup
            except Exception:
                pass
        _force_redraw(area)

    # Difference matte: pixels that change between the two world swaps are
    # background (transparent); pixels that stay constant are foreground geometry.
    diff = np.abs(magenta[:, :, :3] - green[:, :, :3]).max(axis=2)
    alpha = 1.0 - np.clip(diff * 4.0, 0.0, 1.0)
    out = magenta.copy()
    out[:, :, 3] = alpha
    np.clip(out, 0.0, 1.0, out=out)
    return out


def _force_redraw(area):
    area.tag_redraw()
    try:
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# PNG write via Blender's image API
# ---------------------------------------------------------------------------

def _write_array_to_png(arr: np.ndarray, filepath: str):
    h, w, _ = arr.shape
    img = bpy.data.images.new(
        name=os.path.basename(filepath),
        width=w,
        height=h,
        alpha=True,
    )
    try:
        flipped = np.flipud(arr).astype(np.float32)  # Blender wants bottom-up
        img.pixels = flipped.ravel().tolist()
        img.filepath_raw = filepath
        img.file_format = 'PNG'
        img.alpha_mode = 'STRAIGHT'
        img.save()
    finally:
        bpy.data.images.remove(img)


# ---------------------------------------------------------------------------
# Clipboard
# ---------------------------------------------------------------------------

def _copy_image_to_clipboard(filepath: str) -> bool:
    if sys.platform == "darwin":
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
    return False


# ---------------------------------------------------------------------------
# Capture flow
# ---------------------------------------------------------------------------

_METHOD_DISPATCH = {
    "OFFSCREEN_SOLID":            _capture_offscreen_solid,
    "OFFSCREEN_MATERIAL":         _capture_offscreen_material,
    "SCREEN_CAPTURE":             _capture_screen_capture,
    "CRYPTOMATTE_OFFSCREEN_MASK": _capture_cryptomatte_offscreen_mask,
    "RENDER_OPENGL":              _capture_render_opengl,
    "WORLD_SWAP_DIFF":            _capture_world_swap_diff,
}


def _capture_and_process(
    context,
    area,
    region,
    crop_xywh: tuple,  # (x, y, w, h) in REGION pixels, top-left origin
    out_dir: str,
):
    """Dispatch to the chosen capture method, then crop, save, clipboard."""
    os.makedirs(out_dir, exist_ok=True)

    addon = context.preferences.addons.get(__package__)
    method = "RENDER_OPENGL"
    multiplier = 2
    keep_gizmos = False
    if addon and hasattr(addon, "preferences"):
        prefs = addon.preferences
        method = getattr(prefs, "viewport_capture_method", "RENDER_OPENGL")
        multiplier = int(getattr(prefs, "viewport_capture_resolution_multiplier", 2))
        keep_gizmos = bool(getattr(prefs, "viewport_screenshot_keep_gizmos", False))

    handler = _METHOD_DISPATCH.get(method, _capture_render_opengl)
    full = handler(context, area, region, multiplier, keep_gizmos)

    # Helpers always return an array covering the full region; map crop_xywh
    # (region-space, multiplier=1) to the array's actual resolution.
    img_h, img_w = full.shape[:2]
    sx_f = img_w / max(1, region.width)
    sy_f = img_h / max(1, region.height)

    cx, cy, cw, ch = crop_xywh
    sx = max(0, min(int(cx * sx_f), img_w))
    sy = max(0, min(int(cy * sy_f), img_h))
    sw = max(1, min(int(cw * sx_f), img_w - sx))
    sh = max(1, min(int(ch * sy_f), img_h - sy))

    cropped = full[sy:sy + sh, sx:sx + sw, :].copy()

    # Methods that don't produce alpha → ensure RGB output (alpha=1)
    if method in ("SCREEN_CAPTURE", "RENDER_OPENGL"):
        cropped[:, :, 3] = 1.0

    filename = _build_filename("viewport", method_tag=method)
    final_path = os.path.join(out_dir, filename)
    _write_array_to_png(cropped, final_path)

    clip_ok = _copy_image_to_clipboard(final_path)
    if clip_ok:
        msg = f"Viewport screenshot saved to {final_path} — image copied to clipboard"
    else:
        msg = f"Viewport screenshot saved to {final_path} — clipboard copy unavailable"
    print(f"[no3d_asset_developer] {msg}")
    return final_path, msg


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class NO3D_OT_viewport_screenshot_visible(Operator):
    """Capture the visible 3D viewport as a transparent PNG."""
    bl_idname = "no3d.viewport_screenshot_visible"
    bl_label = "Capture Visible Area"
    bl_description = (
        "Render the entire visible 3D viewport with transparent background "
        "as a PNG, copy to clipboard"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    def execute(self, context):
        area = context.area
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        if region is None:
            self.report({'ERROR'}, "No 3D viewport WINDOW region found")
            return {'CANCELLED'}

        out_dir = _resolve_output_dir(context)
        try:
            path, msg = _capture_and_process(
                context, area, region,
                (0, 0, region.width, region.height),
                out_dir,
            )
        except Exception as exc:
            log.exception("Viewport visible screenshot failed")
            self.report({'ERROR'}, f"Screenshot failed: {exc}")
            return {'CANCELLED'}

        self.report({'INFO'}, msg)
        return {'FINISHED'}


class _ViewportRegionCaptureBase(Operator):
    """Shared modal drag-rect machinery for region + thumbnail captures."""
    bl_options = {'REGISTER'}

    SQUARE_LOCK = False
    SHOW_GUIDES = False
    HINT = "Drag to select capture region — ESC to cancel"

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    def invoke(self, context, event):
        self._area = context.area
        self._region = next(r for r in self._area.regions if r.type == 'WINDOW')
        self._dragging = False
        self._start = None  # (rx, ry) in REGION px (bottom-up)
        self._end = None
        self._panning = False
        self._pan_anchor = None
        self._draw_handler = bpy.types.SpaceView3D.draw_handler_add(
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
                bpy.types.SpaceView3D.draw_handler_remove(
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

        # Hold space to translate the marquee
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
                rect = self._region_rect_topdown()
                self._cleanup(context)
                if rect is None or rect[2] < 4 or rect[3] < 4:
                    self.report({'INFO'}, "Region too small — cancelled")
                    return {'CANCELLED'}

                out_dir = _resolve_output_dir(context)
                try:
                    path, msg = _capture_and_process(
                        context, self._area, self._region, rect, out_dir,
                    )
                except Exception as exc:
                    log.exception("Viewport region capture failed")
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

    def _region_rect_topdown(self):
        """Convert the dragged region rectangle to (x, y, w, h) in REGION
        coordinates, top-left origin (so we can crop the rendered offscreen
        which is also top-down after _offscreen_render_viewport flip).
        """
        corners = self._square_corners_region()
        if corners is None:
            return None
        x0, y0, x1, y1 = corners
        rx = min(x0, x1)
        ry_bu = min(y0, y1)  # bottom-up region y of bottom-left corner
        rw = abs(x1 - x0)
        rh = abs(y1 - y0)
        if rw < 1 or rh < 1:
            return None
        # Convert bottom-up region y → top-down image y
        ry_td = self._region.height - (ry_bu + rh)
        return (int(rx), int(ry_td), int(rw), int(rh))

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
        lo_x, hi_x = sorted((x0, x1))
        lo_y, hi_y = sorted((y0, y1))

        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.blend_set('ALPHA')

        # Subtle fill
        fill = [(lo_x, lo_y), (hi_x, lo_y), (hi_x, hi_y), (lo_x, hi_y)]
        fill_batch = batch_for_shader(shader, 'TRI_FAN', {"pos": fill})
        shader.bind()
        shader.uniform_float("color", (1.0, 0.4, 0.0, 0.08))
        fill_batch.draw(shader)

        # Outline
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

            # Margin guide
            gpu.state.line_width_set(1.0)
            inner = [
                (ix0, iy0), (ix1, iy0), (ix1, iy1), (ix0, iy1), (ix0, iy0),
            ]
            inner_batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": inner})
            shader.uniform_float("color", (1.0, 0.85, 0.2, 0.7))
            inner_batch.draw(shader)

            # Corner-to-corner X
            cross = [
                (lo_x, lo_y), (hi_x, hi_y),
                (lo_x, hi_y), (hi_x, lo_y),
            ]
            cross_batch = batch_for_shader(shader, 'LINES', {"pos": cross})
            shader.uniform_float("color", (1.0, 1.0, 1.0, 0.6))
            cross_batch.draw(shader)

        gpu.state.blend_set('NONE')
        gpu.state.line_width_set(1.0)


class NO3D_OT_viewport_screenshot_region(_ViewportRegionCaptureBase):
    """Drag a rectangle in the 3D viewport; capture that region as transparent PNG."""
    bl_idname = "no3d.viewport_screenshot_region"
    bl_label = "Capture Region"
    bl_description = (
        "Drag a rectangle to define the capture region. ESC cancels"
    )

    SQUARE_LOCK = False
    SHOW_GUIDES = False
    HINT = "Drag to select capture region — ESC to cancel"


class NO3D_OT_viewport_screenshot_thumbnail(_ViewportRegionCaptureBase):
    """Square-locked thumbnail capture with center + margin guides."""
    bl_idname = "no3d.viewport_screenshot_thumbnail"
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
    NO3D_OT_viewport_screenshot_visible,
    NO3D_OT_viewport_screenshot_region,
    NO3D_OT_viewport_screenshot_thumbnail,
)


_KEYMAP_BINDINGS = (
    ("no3d.viewport_screenshot_visible",   "C"),
    ("no3d.viewport_screenshot_region",    "R"),
    ("no3d.viewport_screenshot_thumbnail", "T"),
)

_addon_keymaps = []


def _register_keymaps():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc is None:
        return
    km = kc.keymaps.new(name="3D View", space_type="VIEW_3D")
    for op_idname, key in _KEYMAP_BINDINGS:
        kmi = km.keymap_items.new(
            op_idname,
            type=key, value="PRESS",
            ctrl=True, shift=True, alt=True,
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
