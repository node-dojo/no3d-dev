"""
Aspect-ratio screen-space overlay system.

Two visible elements are drawn over every editor area in the active window
when the master toggle is on:

  1. A small pill-shaped readout in the corner of each area closest to the
     mouse cursor, showing "WxH . a:b" (pixel size + decimal aspect).
  2. Centered dotted rectangles for each enabled aspect-ratio preset,
     scaled to fit within ~90 % of the area's smaller dimension. Each
     rectangle has a small "name 16:9" label at its top-left.

A modal operator runs a 30 fps timer that:
  * Tracks the mouse position from MOUSEMOVE / TIMER events so the corner
    readout follows the cursor across windows / areas.
  * Snapshots every area's (width, height) each tick, detects when an area
    just stopped resizing, and -- if the resulting dim is within
    aspect_snap_threshold_px of producing an enabled preset aspect --
    issues a corrective bpy.ops.screen.area_move to snap to the preset.

This file is purely additive. It never touches viewport_format.PRESETS or
any existing handler. All draw handlers and the timer are tracked in
module-level lists and torn down cleanly in unregister().
"""

from __future__ import annotations

import logging
import math
import time

import bpy
import blf
import gpu
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Operator, PropertyGroup, UIList
from gpu_extras.batch import batch_for_shader

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Built-in presets
# ---------------------------------------------------------------------------
#
# (key, label, w, h, pref_visibility_attr)
#
# These four are always present in the AddonPreferences UI as fixed
# toggles -- the user can hide/show them but cannot delete them.

BUILTIN_PRESETS = (
    ("PORTRAIT_9_16",  "Portrait 9:16",  9,  16, "show_preset_9_16"),
    ("FEED_4_5",       "Feed 4:5",       4,  5,  "show_preset_4_5"),
    ("SQUARE_1_1",     "Square 1:1",     1,  1,  "show_preset_1_1"),
    ("LANDSCAPE_16_9", "Landscape 16:9", 16, 9,  "show_preset_16_9"),
)


# Distinct, clearly different swatches for preset rectangles (RGB at 100%;
# alpha is applied at draw time).
PRESET_COLORS = (
    (0.20, 0.85, 0.95),  # cyan
    (0.95, 0.30, 0.85),  # magenta
    (0.95, 0.90, 0.20),  # yellow
    (0.40, 0.95, 0.30),  # lime
    (0.95, 0.55, 0.20),  # orange
)


# Areas we never draw into.
SKIP_AREA_TYPES = {'TOPBAR', 'STATUSBAR'}


# Space types we register a draw handler on. Each one is given two
# handlers: the readout (corner pill) + the rectangles.
DRAW_SPACE_TYPE_NAMES = (
    'SpaceView3D',
    'SpaceNodeEditor',
    'SpaceImageEditor',
    'SpaceProperties',
    'SpaceOutliner',
    'SpaceTextEditor',
    'SpaceFileBrowser',
    'SpaceSpreadsheet',
    'SpaceSequenceEditor',
    'SpaceClipEditor',
    'SpaceGraphEditor',
    'SpaceDopeSheetEditor',
    'SpaceNLA',
    'SpaceConsole',
    'SpacePreferences',
    'SpaceInfo',
)


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

# (space_type_class, handler_object, region_type) so we can remove cleanly.
_draw_handlers: list[tuple[type, object, str]] = []

# (area_dim_history) used by the snap detector. Keyed by id(area).
# Value: dict(w=int, h=int, last_change_t=float, settled=bool, edge_w=str|None,
#             edge_h=str|None).
_area_state: dict[int, dict] = {}

# Last known mouse position in WINDOW pixels (window object captured too).
_mouse_state: dict = {
    "window": None,  # bpy.types.Window
    "x": 0,
    "y": 0,
}

# Modal operator running flag. Survives reload via WindowManager prop, but
# the running modal is module-state only -- on reload, the prop is reset.
_modal_running = False


# ---------------------------------------------------------------------------
# Property groups (custom presets)
# ---------------------------------------------------------------------------


class NO3D_AspectCustomPreset(PropertyGroup):
    """One row of the custom aspect-preset list, stored on AddonPreferences."""

    name: StringProperty(
        name="Name",
        description="Display name for this preset",
        default="Custom",
    )
    width: IntProperty(
        name="Width",
        description="Aspect-ratio width component",
        default=16,
        min=1,
        max=10000,
    )
    height: IntProperty(
        name="Height",
        description="Aspect-ratio height component",
        default=9,
        min=1,
        max=10000,
    )
    show: BoolProperty(
        name="Show",
        description="Draw this preset's rectangle in the overlay",
        default=True,
    )


# ---------------------------------------------------------------------------
# Preset-list helpers
# ---------------------------------------------------------------------------


def _addon_prefs():
    """Return our AddonPreferences instance, or None."""
    addon = bpy.context.preferences.addons.get("no3d_asset_developer")
    if not addon:
        return None
    return getattr(addon, "preferences", None)


def _enabled_presets():
    """Return list of (label, w, h) that the user has visible right now.

    Built-ins come first (in BUILTIN_PRESETS order), then the custom
    presets in their list order. Used by both the rectangle drawer and
    the snap detector so they agree on what's "active".
    """
    out: list[tuple[str, int, int]] = []
    prefs = _addon_prefs()
    if prefs is None:
        return out
    for _key, label, w, h, attr in BUILTIN_PRESETS:
        if getattr(prefs, attr, True):
            out.append((label, int(w), int(h)))
    # Custom presets
    for cp in getattr(prefs, "aspect_custom_presets", []):
        if not cp.show:
            continue
        if cp.width <= 0 or cp.height <= 0:
            continue
        out.append((cp.name or "Custom", int(cp.width), int(cp.height)))
    return out


def _gcd(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return max(1, abs(a))


def _aspect_str(w: int, h: int) -> str:
    g = _gcd(int(w), int(h))
    return f"{int(w) // g}:{int(h) // g}"


# ---------------------------------------------------------------------------
# Drawing primitives
# ---------------------------------------------------------------------------


_SHADER = None


def _shader():
    """Lazy UNIFORM_COLOR shader; can't build at import time."""
    global _SHADER
    if _SHADER is None:
        _SHADER = gpu.shader.from_builtin('UNIFORM_COLOR')
    return _SHADER


def _draw_rect_filled(x: float, y: float, w: float, h: float, color):
    sh = _shader()
    verts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    indices = [(0, 1, 2), (0, 2, 3)]
    batch = batch_for_shader(sh, 'TRIS', {"pos": verts}, indices=indices)
    sh.bind()
    sh.uniform_float("color", color)
    batch.draw(sh)


def _draw_rounded_rect_filled(
    x: float, y: float, w: float, h: float, radius: float, color, segments: int = 6
):
    """Approximate a rounded rect with a triangle fan around its center.

    Cheap approximation: corners are each ``segments`` short segments
    sampled around 90 deg. Good enough for a stat-style background pill.
    """
    if w <= 0 or h <= 0:
        return
    radius = max(0.0, min(radius, min(w, h) * 0.5))
    cx = x + w * 0.5
    cy = y + h * 0.5

    # Corner centers (anchor points for each rounded corner)
    cl = x + radius
    cr = x + w - radius
    cb = y + radius
    ct = y + h - radius

    pts: list[tuple[float, float]] = []

    # Bottom-right corner (angles -90 -> 0)
    for i in range(segments + 1):
        t = -math.pi / 2 + (math.pi / 2) * (i / segments)
        pts.append((cr + radius * math.cos(t), cb + radius * math.sin(t)))
    # Top-right corner (0 -> 90)
    for i in range(segments + 1):
        t = (math.pi / 2) * (i / segments)
        pts.append((cr + radius * math.cos(t), ct + radius * math.sin(t)))
    # Top-left corner (90 -> 180)
    for i in range(segments + 1):
        t = math.pi / 2 + (math.pi / 2) * (i / segments)
        pts.append((cl + radius * math.cos(t), ct + radius * math.sin(t)))
    # Bottom-left corner (180 -> 270)
    for i in range(segments + 1):
        t = math.pi + (math.pi / 2) * (i / segments)
        pts.append((cl + radius * math.cos(t), cb + radius * math.sin(t)))

    # Triangle fan: center + perimeter
    verts = [(cx, cy)] + pts + [pts[0]]
    sh = _shader()
    batch = batch_for_shader(sh, 'TRI_FAN', {"pos": verts})
    sh.bind()
    sh.uniform_float("color", color)
    batch.draw(sh)


def _dashed_segments(x0: float, y0: float, x1: float, y1: float,
                     dash: float, gap: float) -> list[tuple[float, float]]:
    """Walk a line, emit point pairs for a dashed `LINES` batch."""
    out: list[tuple[float, float]] = []
    dx = x1 - x0
    dy = y1 - y0
    length = math.hypot(dx, dy)
    if length <= 0:
        return out
    ux = dx / length
    uy = dy / length
    period = max(1.0, dash + gap)
    t = 0.0
    while t < length:
        t_end = min(length, t + dash)
        out.append((x0 + ux * t, y0 + uy * t))
        out.append((x0 + ux * t_end, y0 + uy * t_end))
        t += period
    return out


def _draw_dashed_rect_outline(
    x: float, y: float, w: float, h: float, color, dash: float = 6.0, gap: float = 4.0
):
    """Draw a 1 px dashed rectangle outline using a single LINES batch."""
    if w <= 0 or h <= 0:
        return
    segs: list[tuple[float, float]] = []
    segs += _dashed_segments(x,     y,     x + w, y,     dash, gap)  # bottom
    segs += _dashed_segments(x + w, y,     x + w, y + h, dash, gap)  # right
    segs += _dashed_segments(x + w, y + h, x,     y + h, dash, gap)  # top
    segs += _dashed_segments(x,     y + h, x,     y,     dash, gap)  # left
    if not segs:
        return
    sh = _shader()
    batch = batch_for_shader(sh, 'LINES', {"pos": segs})
    gpu.state.line_width_set(1.0)
    sh.bind()
    sh.uniform_float("color", color)
    batch.draw(sh)


def _draw_dashed_x(
    x: float, y: float, w: float, h: float, color, dash: float = 6.0, gap: float = 4.0
):
    """Draw a dashed corner-to-corner X inside the given rectangle.

    Used so the rectangle stays visible when its outline is flush with
    the area's edges (where Blender's chrome would otherwise hide it).
    """
    if w <= 0 or h <= 0:
        return
    segs: list[tuple[float, float]] = []
    segs += _dashed_segments(x,     y,     x + w, y + h, dash, gap)
    segs += _dashed_segments(x,     y + h, x + w, y,     dash, gap)
    if not segs:
        return
    sh = _shader()
    batch = batch_for_shader(sh, 'LINES', {"pos": segs})
    gpu.state.line_width_set(1.0)
    sh.bind()
    sh.uniform_float("color", color)
    batch.draw(sh)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _main_region(area):
    """Return the WINDOW region (the central drawing region) for an area.

    Falls back to the largest region if for some reason there is no
    region of type WINDOW.
    """
    win_regions = [r for r in area.regions if r.type == 'WINDOW']
    if win_regions:
        return win_regions[0]
    if area.regions:
        return max(area.regions, key=lambda r: r.width * r.height)
    return None


def _ui_scale() -> float:
    try:
        return bpy.context.preferences.view.ui_scale
    except Exception:
        return 1.0


def _font_size_scaled(base_pt: float) -> float:
    return max(8.0, base_pt * _ui_scale())


# ---------------------------------------------------------------------------
# Corner readout (label that follows mouse)
# ---------------------------------------------------------------------------


def _draw_corner_readout(area):
    """Draw the WxH . a:b pill in the area corner closest to the mouse.

    Coords here are region-local pixels (POST_PIXEL handler).
    """
    region = _main_region(area)
    if region is None or region.width < 40 or region.height < 24:
        return

    # Mouse window-pixel coords -> area-local
    win = _mouse_state.get("window")
    mx_win = _mouse_state.get("x", 0)
    my_win = _mouse_state.get("y", 0)
    if win is None:
        # Default to top-left of area until we have a real mouse pos
        mx_win = area.x + 1
        my_win = area.y + area.height - 1

    # Pick which area corner: based on mouse position relative to
    # area center (full area, not just region).
    area_cx = area.x + area.width * 0.5
    area_cy = area.y + area.height * 0.5
    is_right = mx_win >= area_cx
    is_top = my_win >= area_cy

    # Build the label text using the WINDOW region size (the visible
    # drawing surface for that editor; matches what a user thinks of
    # as the editor's content pixels).
    w = int(region.width)
    h = int(region.height)
    if h <= 0:
        return
    aspect = w / h
    label = f"{w}x{h}  {_aspect_str(w, h)}  ({aspect:.2f}:1)"

    # Font setup
    font_id = 0
    font_pt = _font_size_scaled(11.0)
    blf.size(font_id, font_pt)
    text_w, text_h = blf.dimensions(font_id, label)

    pad_x = 8.0
    pad_y = 5.0
    margin = 6.0  # distance from area corner

    pill_w = text_w + pad_x * 2
    pill_h = text_h + pad_y * 2

    # Convert from area-local to region-local coords.
    # POST_PIXEL drawing origin is region (0,0) at region.x, region.y.
    # Pill positions inside the AREA's chosen corner, then we translate.
    if is_right:
        pill_x_area = area.width - pill_w - margin
    else:
        pill_x_area = margin
    if is_top:
        pill_y_area = area.height - pill_h - margin
    else:
        pill_y_area = margin

    # Translate area-local -> region-local
    pill_x = (area.x + pill_x_area) - region.x
    pill_y = (area.y + pill_y_area) - region.y

    # Background pill
    _draw_rounded_rect_filled(
        pill_x, pill_y, pill_w, pill_h,
        radius=min(pill_h, pill_w) * 0.5,
        color=(0.0, 0.0, 0.0, 0.55),
        segments=4,
    )

    # Text
    blf.color(font_id, 1.0, 1.0, 1.0, 0.95)
    blf.position(font_id, pill_x + pad_x, pill_y + pad_y, 0)
    blf.draw(font_id, label)


# ---------------------------------------------------------------------------
# Aspect-ratio rectangles (centered, per area)
# ---------------------------------------------------------------------------


def _draw_aspect_rects(area):
    """Draw centered preset rectangles inside an area's WINDOW region."""
    region = _main_region(area)
    if region is None:
        return
    rw = region.width
    rh = region.height
    if rw < 40 or rh < 30:
        return

    presets = _enabled_presets()
    if not presets:
        return

    # Center of region (region-local)
    cx = rw * 0.5
    cy = rh * 0.5

    # Fill the region edge-to-edge (whichever axis the aspect makes
    # constraining). When the rect ends up flush with the region edges,
    # the dashed outline can be hidden by Blender's chrome -- the
    # corner-to-corner X drawn below keeps the preset visible.
    fit_w = float(rw)
    fit_h = float(rh)

    font_id = 0
    label_pt = _font_size_scaled(10.0)
    blf.size(font_id, label_pt)

    for i, (name, aw, ah) in enumerate(presets):
        if aw <= 0 or ah <= 0:
            continue
        ar = aw / ah
        # Fit a rect of aspect AR inside (fit_w, fit_h)
        if (fit_w / fit_h) >= ar:
            # Region is wider than preset -> height-bound
            box_h = fit_h
            box_w = box_h * ar
        else:
            box_w = fit_w
            box_h = box_w / ar

        x = cx - box_w * 0.5
        y = cy - box_h * 0.5

        rgb = PRESET_COLORS[i % len(PRESET_COLORS)]
        rgba = (rgb[0], rgb[1], rgb[2], 0.7)

        _draw_dashed_rect_outline(x, y, box_w, box_h, rgba, dash=6.0, gap=4.0)
        # Corner-to-corner X so the rect stays visible when its outline
        # is flush with the region edges (Blender's chrome can clip the
        # outline; the X always lives in the interior).
        _draw_dashed_x(x, y, box_w, box_h, rgba, dash=8.0, gap=6.0)

        # Label at top-left of the box, pinned just inside
        ratio_str = _aspect_str(aw, ah)
        text = f"{name}  {ratio_str}"
        text_w, text_h = blf.dimensions(font_id, text)
        # Background chip behind label
        chip_pad_x = 4.0
        chip_pad_y = 2.0
        chip_w = text_w + chip_pad_x * 2
        chip_h = text_h + chip_pad_y * 2
        chip_x = x + 4.0
        chip_y = y + box_h - chip_h - 4.0
        if chip_y < y:  # very small box
            chip_y = y + 2.0
        _draw_rect_filled(chip_x, chip_y, chip_w, chip_h, (0.0, 0.0, 0.0, 0.55))
        blf.color(font_id, rgb[0], rgb[1], rgb[2], 0.95)
        blf.position(font_id, chip_x + chip_pad_x, chip_y + chip_pad_y, 0)
        blf.draw(font_id, text)


# ---------------------------------------------------------------------------
# Per-area draw entrypoint
# ---------------------------------------------------------------------------


def _draw_callback_for_space():
    """Build a closure-free draw callback. Reads the WM toggle each call.

    Inside a POST_PIXEL draw handler, ``bpy.context.area`` and
    ``bpy.context.region`` correctly identify the area + region being
    drawn -- but ``area.spaces.active`` is NOT the same Python object
    as ``bpy.context.space_data`` (Blender wraps the active space in a
    fresh Python wrapper for each draw call), so we can't match by
    identity. Reading ``bpy.context.area`` directly is the documented
    path and is what we use.
    """
    def _draw():
        # Master toggle gate
        wm = bpy.context.window_manager
        if not wm or not getattr(wm, "no3d_aspect_overlay_active", False):
            return

        area = bpy.context.area
        if area is None:
            return
        if area.type in SKIP_AREA_TYPES:
            return

        # Save GPU state we touch
        try:
            gpu.state.blend_set('ALPHA')
            try:
                _draw_aspect_rects(area)
                _draw_corner_readout(area)
            finally:
                gpu.state.blend_set('NONE')
        except Exception as exc:
            log.debug("aspect overlay draw failed: %s", exc)

    return _draw


# ---------------------------------------------------------------------------
# Snap-on-resize-release detector
# ---------------------------------------------------------------------------


# How long the area's dims must stay frozen before we consider the drag
# released. 150 ms is roughly Blender's UI redraw settle time after the
# user lifts the mouse from an edge.
_SETTLE_T = 0.15


def _snapshot_areas():
    """Walk every window/area, run the snap detector. Called from TIMER."""
    prefs = _addon_prefs()
    if prefs is None:
        return
    if not getattr(prefs, "aspect_snap_enabled", True):
        return
    threshold = max(0, int(getattr(prefs, "aspect_snap_threshold_px", 12)))
    if threshold <= 0:
        return

    wm = bpy.context.window_manager
    if not wm:
        return

    now = time.monotonic()

    for win in wm.windows:
        screen = win.screen
        for area in screen.areas:
            if area.type in SKIP_AREA_TYPES:
                continue
            key = id(area)
            cur_w = int(area.width)
            cur_h = int(area.height)
            st = _area_state.get(key)
            if st is None:
                _area_state[key] = {
                    "w": cur_w, "h": cur_h,
                    "last_change_t": now,
                    "settled": True,
                }
                continue
            if cur_w != st["w"] or cur_h != st["h"]:
                # Dim changed since last tick. Mark unsettled.
                st["w"] = cur_w
                st["h"] = cur_h
                st["last_change_t"] = now
                st["settled"] = False
                continue
            # No change since last tick.
            if st["settled"]:
                continue
            if (now - st["last_change_t"]) < _SETTLE_T:
                continue
            # Just settled -> try a snap.
            st["settled"] = True
            try:
                _try_snap_area(win, screen, area, threshold)
            except Exception as exc:
                log.warning("aspect snap failed: %s", exc)


def _try_snap_area(window, screen, area, threshold_px: int) -> None:
    """If `area`'s current dim is within threshold of an enabled preset's
    aspect ratio, issue a corrective screen.area_move via deferred timer.

    Strategy:
      For each enabled preset (a:b), and for both orientations (a:b and
      b:a), compute the ideal width that would yield that exact ratio at
      the area's current height, and the ideal height at its current
      width. The smaller of the two corrections is the snap candidate.
      Pick the closest preset overall, and if its required correction is
      <= threshold_px, schedule the move.
    """
    presets = _enabled_presets()
    if not presets:
        return

    cur_w = int(area.width)
    cur_h = int(area.height)
    if cur_w < 40 or cur_h < 40:
        return

    best = None  # (delta_px, axis: 'w'|'h', target_dim, edge)
    for _name, aw, ah in presets:
        if aw <= 0 or ah <= 0:
            continue
        for ratio in (aw / ah, ah / aw):
            # Width snap at current height: target_w / cur_h = ratio
            target_w = int(round(cur_h * ratio))
            dw = target_w - cur_w
            if abs(dw) <= threshold_px and abs(dw) >= 1:
                if best is None or abs(dw) < abs(best[0]):
                    best = (dw, 'w', target_w, None)
            # Height snap at current width: cur_w / target_h = ratio
            if ratio > 0:
                target_h = int(round(cur_w / ratio))
                dh = target_h - cur_h
                if abs(dh) <= threshold_px and abs(dh) >= 1:
                    if best is None or abs(dh) < abs(best[0]):
                        best = (dh, 'h', target_h, None)

    if best is None:
        return

    delta_px, axis, target_dim, _ = best

    # Pick which edge to nudge. We need a neighbour on that edge for
    # area_move to do anything. Prefer right/bottom (matching the
    # viewport_format.py convention) and fall back to the opposite.
    if axis == 'w':
        edge = _pick_width_edge(area, screen)
    else:
        edge = _pick_height_edge(area, screen)
    if edge is None:
        return

    # growth in physical px (positive = grow area on that axis)
    growth = delta_px

    # Defer the actual cursor warp + area_move (same recipe as
    # viewport_format._move_edge but inlined to avoid coupling to that
    # module's internal API).
    def _do_move():
        try:
            x, y = _edge_point(area, edge)
            window.cursor_warp(x, y)
            signed = growth if edge in ('right', 'top') else -growth
            with bpy.context.temp_override(window=window, screen=screen, area=area):
                bpy.ops.screen.area_move(x=x, y=y, delta=signed)
        except Exception as exc:
            log.debug("snap area_move failed: %s", exc)
        finally:
            # Refresh stored dims to the new size so we don't snap-loop.
            key = id(area)
            st = _area_state.get(key)
            if st is not None:
                st["w"] = int(area.width)
                st["h"] = int(area.height)
                st["last_change_t"] = time.monotonic()
                st["settled"] = True
        return None

    bpy.app.timers.register(_do_move, first_interval=0.02)


# Edge / neighbour discovery (mini-copies of the viewport_format.py
# helpers, kept local so this module is self-contained).

_EDGE_TOL = 2


def _overlap_y(a, b) -> bool:
    return not (b.y + b.height <= a.y or b.y >= a.y + a.height)


def _overlap_x(a, b) -> bool:
    return not (b.x + b.width <= a.x or b.x >= a.x + a.width)


def _has_neighbor_right(area, screen) -> bool:
    right = area.x + area.width
    return any(
        other is not area
        and abs(other.x - right) <= _EDGE_TOL
        and _overlap_y(area, other)
        for other in screen.areas
    )


def _has_neighbor_left(area, screen) -> bool:
    return any(
        other is not area
        and abs((other.x + other.width) - area.x) <= _EDGE_TOL
        and _overlap_y(area, other)
        for other in screen.areas
    )


def _has_neighbor_top(area, screen) -> bool:
    top = area.y + area.height
    return any(
        other is not area
        and abs(other.y - top) <= _EDGE_TOL
        and _overlap_x(area, other)
        for other in screen.areas
    )


def _has_neighbor_bottom(area, screen) -> bool:
    return any(
        other is not area
        and abs((other.y + other.height) - area.y) <= _EDGE_TOL
        and _overlap_x(area, other)
        for other in screen.areas
    )


def _pick_width_edge(area, screen):
    if _has_neighbor_right(area, screen):
        return 'right'
    if _has_neighbor_left(area, screen):
        return 'left'
    return None


def _pick_height_edge(area, screen):
    if _has_neighbor_bottom(area, screen):
        return 'bottom'
    if _has_neighbor_top(area, screen):
        return 'top'
    return None


def _edge_point(area, edge: str):
    if edge == 'right':
        return area.x + area.width, area.y + area.height // 2
    if edge == 'left':
        return area.x, area.y + area.height // 2
    if edge == 'top':
        return area.x + area.width // 2, area.y + area.height
    if edge == 'bottom':
        return area.x + area.width // 2, area.y
    raise ValueError(f"Unknown edge: {edge}")


# ---------------------------------------------------------------------------
# Modal operator: timer driver
# ---------------------------------------------------------------------------


class NO3D_OT_aspect_overlay_modal(Operator):
    """Drive the aspect overlay: track mouse + run snap detector each tick.

    Runs as long as no3d_aspect_overlay_active is True. The N-panel
    toggle starts/stops it via NO3D_OT_aspect_overlay_toggle.
    """

    bl_idname = "no3d.aspect_overlay_modal"
    bl_label = "Aspect Overlay (modal)"
    bl_options = {'INTERNAL'}

    _timer = None

    def modal(self, context, event):
        wm = context.window_manager

        # Bail out cleanly if the user toggled off.
        if not getattr(wm, "no3d_aspect_overlay_active", False):
            return self._finish(context, cancelled=False)

        if event.type == 'MOUSEMOVE':
            _mouse_state["window"] = context.window
            _mouse_state["x"] = event.mouse_x
            _mouse_state["y"] = event.mouse_y
            # Tag visible areas in this window for redraw so the corner
            # pill follows the cursor across editors.
            if context.window:
                for a in context.window.screen.areas:
                    if a.type not in SKIP_AREA_TYPES:
                        a.tag_redraw()
            return {'PASS_THROUGH'}

        if event.type == 'TIMER':
            # Snap detector
            _snapshot_areas()
            # Keep mouse fresh (event.mouse_x is valid on TIMER too)
            _mouse_state["window"] = context.window
            _mouse_state["x"] = event.mouse_x
            _mouse_state["y"] = event.mouse_y
            # Periodic redraw: tag every area in every window so resize
            # changes are picked up everywhere.
            for win in context.window_manager.windows:
                for a in win.screen.areas:
                    if a.type not in SKIP_AREA_TYPES:
                        a.tag_redraw()
            return {'PASS_THROUGH'}

        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        global _modal_running
        if _modal_running:
            # Already running -- don't start a second instance.
            return {'CANCELLED'}
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.033, window=context.window)
        wm.modal_handler_add(self)
        _modal_running = True
        return {'RUNNING_MODAL'}

    def _finish(self, context, cancelled: bool):
        global _modal_running
        wm = context.window_manager
        if self._timer is not None:
            try:
                wm.event_timer_remove(self._timer)
            except Exception:
                pass
            self._timer = None
        _modal_running = False
        # Force a final redraw so handlers paint nothing.
        if context.window:
            for a in context.window.screen.areas:
                if a.type not in SKIP_AREA_TYPES:
                    a.tag_redraw()
        return {'CANCELLED'} if cancelled else {'FINISHED'}


# ---------------------------------------------------------------------------
# Toggle operator (called by the N-panel checkbox via update callback)
# ---------------------------------------------------------------------------


def _on_overlay_active_changed(self, context):
    """WindowManager.no3d_aspect_overlay_active update callback."""
    if self.no3d_aspect_overlay_active:
        # Make sure handlers are in place + start the modal timer.
        _ensure_draw_handlers()
        # Only one modal at a time.
        if not _modal_running:
            try:
                bpy.ops.no3d.aspect_overlay_modal('INVOKE_DEFAULT')
            except Exception as exc:
                log.warning("Could not start aspect overlay modal: %s", exc)
    else:
        # Modal will exit on its next tick (it polls the prop). Just
        # request redraws so the screen clears.
        for win in context.window_manager.windows:
            for a in win.screen.areas:
                if a.type not in SKIP_AREA_TYPES:
                    a.tag_redraw()


# ---------------------------------------------------------------------------
# Custom-preset list operators
# ---------------------------------------------------------------------------


class NO3D_OT_aspect_preset_add(Operator):
    """Add a new custom aspect preset (default 16:9, auto-named)."""
    bl_idname = "no3d.aspect_preset_add"
    bl_label = "Add Custom Aspect Preset"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        prefs = _addon_prefs()
        if prefs is None:
            self.report({'ERROR'}, "Addon preferences unavailable")
            return {'CANCELLED'}
        coll = prefs.aspect_custom_presets
        n = 1
        existing = {cp.name for cp in coll}
        while f"Custom {n}" in existing:
            n += 1
        item = coll.add()
        item.name = f"Custom {n}"
        item.width = 16
        item.height = 9
        item.show = True
        # Select the new one in the UIList for immediate editing.
        prefs.aspect_custom_presets_index = len(coll) - 1
        return {'FINISHED'}


class NO3D_OT_aspect_preset_remove(Operator):
    """Remove a custom aspect preset by index."""
    bl_idname = "no3d.aspect_preset_remove"
    bl_label = "Remove Custom Aspect Preset"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=-1)

    def execute(self, context):
        prefs = _addon_prefs()
        if prefs is None:
            self.report({'ERROR'}, "Addon preferences unavailable")
            return {'CANCELLED'}
        idx = self.index if self.index >= 0 else prefs.aspect_custom_presets_index
        coll = prefs.aspect_custom_presets
        if 0 <= idx < len(coll):
            coll.remove(idx)
            prefs.aspect_custom_presets_index = max(0, min(idx, len(coll) - 1))
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# UIList for custom presets
# ---------------------------------------------------------------------------


class NO3D_UL_aspect_custom_presets(UIList):
    """One row per custom aspect preset: visibility, name, w, h, delete."""

    bl_idname = "NO3D_UL_aspect_custom_presets"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "show", text="", icon='HIDE_OFF' if item.show else 'HIDE_ON', emboss=False)
        row.prop(item, "name", text="", emboss=True)
        row.prop(item, "width", text="W")
        row.prop(item, "height", text="H")
        op = row.operator("no3d.aspect_preset_remove", text="", icon='TRASH')
        op.index = index


# ---------------------------------------------------------------------------
# Draw-handler registration
# ---------------------------------------------------------------------------


def _ensure_draw_handlers():
    """Idempotent: make sure each space type has its draw handler attached."""
    if _draw_handlers:
        return  # already attached

    for type_name in DRAW_SPACE_TYPE_NAMES:
        space_cls = getattr(bpy.types, type_name, None)
        if space_cls is None:
            continue
        try:
            cb = _draw_callback_for_space()
            handler = space_cls.draw_handler_add(cb, (), 'WINDOW', 'POST_PIXEL')
            _draw_handlers.append((space_cls, handler, 'WINDOW'))
        except Exception as exc:
            log.warning("Could not add draw handler for %s: %s", type_name, exc)


def _remove_draw_handlers():
    """Tear down every handler we ever added. Always runs in unregister."""
    for space_cls, handler, region_type in _draw_handlers:
        try:
            space_cls.draw_handler_remove(handler, region_type)
        except Exception as exc:
            log.debug("Could not remove draw handler from %s: %s", space_cls, exc)
    _draw_handlers.clear()


# ---------------------------------------------------------------------------
# N-panel section (drawn into the existing No3D Dev category by ui.py)
# ---------------------------------------------------------------------------


def draw_aspect_overlay_section(layout, context):
    """Public draw function -- ui.py mounts this in its own panel.

    Kept here so the section's logic and prefs access live alongside the
    feature it controls.
    """
    wm = context.window_manager
    prefs = _addon_prefs()

    box = layout.box()
    row = box.row(align=True)
    row.prop(
        wm, "no3d_aspect_overlay_active",
        text="Show Overlay",
        icon='HIDE_OFF' if wm.no3d_aspect_overlay_active else 'HIDE_ON',
        toggle=True,
    )

    if prefs is None:
        return

    # Snap controls (collapsible)
    snap_box = layout.box()
    header = snap_box.row(align=True)
    header.prop(
        prefs, "aspect_section_snap_expanded",
        text="Magnetic Snap on Resize",
        icon='TRIA_DOWN' if prefs.aspect_section_snap_expanded else 'TRIA_RIGHT',
        emboss=False,
    )
    if prefs.aspect_section_snap_expanded:
        snap_box.prop(prefs, "aspect_snap_enabled", text="Snap on edge release")
        sub = snap_box.row()
        sub.enabled = prefs.aspect_snap_enabled
        sub.prop(prefs, "aspect_snap_threshold_px", slider=True)

    # Built-in presets (collapsible)
    bi_box = layout.box()
    header = bi_box.row(align=True)
    header.prop(
        prefs, "aspect_section_builtin_expanded",
        text="Built-in Presets",
        icon='TRIA_DOWN' if prefs.aspect_section_builtin_expanded else 'TRIA_RIGHT',
        emboss=False,
    )
    if prefs.aspect_section_builtin_expanded:
        col = bi_box.column(align=True)
        for _key, label, _w, _h, attr in BUILTIN_PRESETS:
            col.prop(prefs, attr, text=label)

    # Custom presets (collapsible)
    cu_box = layout.box()
    header = cu_box.row(align=True)
    header.prop(
        prefs, "aspect_section_custom_expanded",
        text="Custom Presets",
        icon='TRIA_DOWN' if prefs.aspect_section_custom_expanded else 'TRIA_RIGHT',
        emboss=False,
    )
    if prefs.aspect_section_custom_expanded:
        cu_box.template_list(
            "NO3D_UL_aspect_custom_presets", "",
            prefs, "aspect_custom_presets",
            prefs, "aspect_custom_presets_index",
            rows=3,
        )
        cu_box.operator(
            "no3d.aspect_preset_add",
            text="Add Preset",
            icon='ADD',
        )

    # Footer hints
    sub = layout.column(align=True)
    sub.scale_y = 0.85
    sub.label(text="Toggle paints rectangles in every editor area.", icon='INFO')
    sub.label(text="Pixel readout follows your mouse.")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


_classes = (
    NO3D_AspectCustomPreset,
    NO3D_UL_aspect_custom_presets,
    NO3D_OT_aspect_preset_add,
    NO3D_OT_aspect_preset_remove,
    NO3D_OT_aspect_overlay_modal,
)


def register_wm_props():
    bpy.types.WindowManager.no3d_aspect_overlay_active = BoolProperty(
        name="Show Aspect Overlay",
        description=(
            "Draw aspect-ratio guides and a per-area pixel readout over "
            "every editor in this window"
        ),
        default=False,
        update=_on_overlay_active_changed,
    )


def unregister_wm_props():
    try:
        delattr(bpy.types.WindowManager, "no3d_aspect_overlay_active")
    except AttributeError:
        pass


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    register_wm_props()
    # IMPORTANT: defer attaching draw handlers and starting the modal
    # until the user actually toggles the overlay on. Attaching at
    # register() means the handlers fire even when the feature is off,
    # which is wasteful and risky if the addon errors out mid-load.


def unregister():
    # 1) Make sure no modal is running. The modal polls the WM bool, so
    #    flipping it false is the cleanest exit.
    try:
        bpy.context.window_manager.no3d_aspect_overlay_active = False
    except Exception:
        pass
    # 2) Remove every draw handler we attached, even if registration was
    #    partial. This is the critical safety step; stale handlers from
    #    a prior load will crash subsequent renders.
    _remove_draw_handlers()
    # 3) Clear cached state.
    _area_state.clear()
    _mouse_state["window"] = None
    # 4) Unregister WM prop + classes.
    unregister_wm_props()
    for cls in reversed(_classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
