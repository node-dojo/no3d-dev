"""
Resize a chosen 3D viewport area inside Blender's main window to match a
content-format aspect ratio. The OS window stays put; neighbouring
editors reflow to give up (or absorb) space.

Implementation: bpy.ops.screen.area_move(x, y, delta) is a modal-style op
that reads the actual mouse cursor position to identify the edge it
operates on. Calling it directly from a Python operator without first
warping the cursor onto the target edge can return FINISHED but no-op,
or return CANCELLED. The reliable recipe (verified empirically against
Blender 5.1):

  1. Warp the cursor to the exact edge midpoint.
  2. Defer area_move via bpy.app.timers so the warp settles first.
  3. From the timer callback, build a temp_override and call area_move.

Sign convention (verified by direct testing):
  right edge:  positive delta grows the area
  left edge:   positive delta shrinks the area
  top edge:    positive delta grows the area
  bottom edge: positive delta shrinks the area

So: signed-delta = (target - current). For right and top edges we pass
that delta directly; for left and bottom edges we negate it.
"""

import logging

import bpy
from bpy.props import EnumProperty
from bpy.types import Operator

log = logging.getLogger(__name__)


# (key, label, description, aspect_w, aspect_h)
PRESETS = [
    ("PORTRAIT_9_16",      "Portrait 9:16",
     "Standard vertical short-form aspect ratio (Reels, Shorts, TikTok)", 9, 16),
    ("INSTAGRAM_REELS",    "Instagram Reels",
     "Identical aspect to Portrait 9:16; named for clarity", 9, 16),
    ("INSTAGRAM_FEED_4_5", "Instagram Feed 4:5",
     "Tall feed-post aspect — fills more screen than square", 4, 5),
    ("SQUARE_1_1",         "Square 1:1",
     "Universal square aspect", 1, 1),
    ("LANDSCAPE_16_9",     "Landscape 16:9",
     "Standard HD horizontal aspect", 16, 9),
]


def _preset_lookup(key: str):
    for k, label, _desc, aw, ah in PRESETS:
        if k == key:
            return label, aw, ah
    return None, None, None


def _enum_items(_self, _context):
    return [
        (k, label, desc, 'OUTPUT', i)
        for i, (k, label, desc, _aw, _ah) in enumerate(PRESETS)
    ]


# ---------------------------------------------------------------------------
# Target-dimension math
# ---------------------------------------------------------------------------

def _compute_target_dims(
    cur_w: int, cur_h: int,
    aspect_w: int, aspect_h: int,
    max_w: int, max_h: int,
):
    """Pick a target (w, h) for the area at the desired aspect.

    Anchors the longer current edge, then scales both dimensions down if
    the matching short edge would exceed available room. Returns ints
    >= 50 px on each axis.
    """
    target_aspect = aspect_w / aspect_h
    if target_aspect < 1.0:
        new_h = cur_h
        new_w = new_h * target_aspect
    elif target_aspect > 1.0:
        new_w = cur_w
        new_h = new_w / target_aspect
    else:
        side = min(cur_w, cur_h)
        new_w = side
        new_h = side

    cap_w = max(1, max_w)
    cap_h = max(1, max_h)
    scale = min(1.0, cap_w / new_w, cap_h / new_h)
    new_w *= scale
    new_h *= scale

    return max(50, int(round(new_w))), max(50, int(round(new_h)))


# ---------------------------------------------------------------------------
# Edge / neighbour discovery
# ---------------------------------------------------------------------------

# Blender draws a 1-px separator between adjacent areas, so neighbours sit
# 1 px apart along the shared axis. Allow a small tolerance.
_EDGE_TOL = 2


def _overlap_y(a, b) -> bool:
    return not (b.y + b.height <= a.y or b.y >= a.y + a.height)


def _overlap_x(a, b) -> bool:
    return not (b.x + b.width <= a.x or b.x >= a.x + a.width)


def _has_neighbor_right(area, screen) -> bool:
    right = area.x + area.width
    return any(
        other is not area and abs(other.x - right) <= _EDGE_TOL and _overlap_y(area, other)
        for other in screen.areas
    )


def _has_neighbor_left(area, screen) -> bool:
    return any(
        other is not area and abs((other.x + other.width) - area.x) <= _EDGE_TOL
        and _overlap_y(area, other)
        for other in screen.areas
    )


def _has_neighbor_top(area, screen) -> bool:
    top = area.y + area.height
    return any(
        other is not area and abs(other.y - top) <= _EDGE_TOL and _overlap_x(area, other)
        for other in screen.areas
    )


def _has_neighbor_bottom(area, screen) -> bool:
    return any(
        other is not area and abs((other.y + other.height) - area.y) <= _EDGE_TOL
        and _overlap_x(area, other)
        for other in screen.areas
    )


# ---------------------------------------------------------------------------
# Edge-move primitive
# ---------------------------------------------------------------------------

def _edge_point(area, edge: str):
    """Return (x, y) midpoint of the named edge, in window pixels."""
    if edge == 'right':
        return area.x + area.width, area.y + area.height // 2
    if edge == 'left':
        return area.x, area.y + area.height // 2
    if edge == 'top':
        return area.x + area.width // 2, area.y + area.height
    if edge == 'bottom':
        return area.x + area.width // 2, area.y
    raise ValueError(f"Unknown edge: {edge}")


def _signed_delta_for_edge(edge: str, signed_growth: int) -> int:
    """Translate "grow area by N" into the area_move delta argument.

    For right/top edges: positive growth = positive delta.
    For left/bottom edges: positive growth = negative delta.
    """
    if edge in ('right', 'top'):
        return signed_growth
    return -signed_growth


def _move_edge(window, screen, area, edge: str, growth: int) -> bool:
    """Warp the cursor to `edge` and run area_move with the appropriate
    signed delta. Must be called inside a timer (so the cursor warp can
    settle before area_move reads it). Returns True if the op didn't
    raise — note the op may itself return CANCELLED in benign cases.
    """
    if growth == 0:
        return True
    x, y = _edge_point(area, edge)
    delta = _signed_delta_for_edge(edge, growth)
    try:
        window.cursor_warp(x, y)
        with bpy.context.temp_override(window=window, screen=screen, area=area):
            bpy.ops.screen.area_move(x=x, y=y, delta=delta)
        return True
    except Exception as exc:
        log.warning("area_move on %s edge failed: %s", edge, exc)
        return False


# ---------------------------------------------------------------------------
# Target-area selection
# ---------------------------------------------------------------------------

def _select_target_area(context):
    """Return (window, screen, area). Prefer the invoking 3D viewport;
    else the largest 3D viewport in the active window.
    """
    window = context.window
    screen = window.screen
    area = context.area
    if area is not None and area.type == 'VIEW_3D':
        return window, screen, area

    candidates = [a for a in screen.areas if a.type == 'VIEW_3D']
    if not candidates:
        return window, screen, None
    candidates.sort(key=lambda a: a.width * a.height, reverse=True)
    return window, screen, candidates[0]


def _pick_width_edge(area, screen):
    """Prefer right edge; fall back to left. Returns edge name or None."""
    if _has_neighbor_right(area, screen):
        return 'right'
    if _has_neighbor_left(area, screen):
        return 'left'
    return None


def _pick_height_edge(area, screen):
    """Prefer bottom edge (so the viewport "grows up"); else top.
    Returns edge name or None.
    """
    if _has_neighbor_bottom(area, screen):
        return 'bottom'
    if _has_neighbor_top(area, screen):
        return 'top'
    return None


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------

class NO3D_OT_apply_viewport_preset(Operator):
    """Reshape a 3D viewport area inside Blender to a content-format aspect."""
    bl_idname = "no3d.apply_viewport_preset"
    bl_label = "Apply Viewport Preset"
    bl_description = (
        "Resize the active 3D viewport area to the preset's aspect ratio. "
        "Neighbouring editors reflow to absorb the change. The OS window "
        "is not moved or resized"
    )
    bl_options = {'REGISTER'}

    preset: EnumProperty(
        name="Preset",
        description="Aspect-ratio preset to apply",
        items=_enum_items,
    )

    @classmethod
    def poll(cls, context):
        return context.window is not None and context.window.screen is not None

    def execute(self, context):
        label, aw, ah = _preset_lookup(self.preset)
        if aw is None:
            self.report({'ERROR'}, f"Unknown preset: {self.preset}")
            return {'CANCELLED'}

        window, screen, area = _select_target_area(context)
        if area is None:
            self.report({'ERROR'}, "No 3D viewport area found")
            return {'CANCELLED'}

        # Available envelope: capped by window dims with a small margin so
        # we never request edges that would push past the global topbar.
        max_w = max(1, window.width - 4)
        max_h = max(1, window.height - 4)

        cur_w, cur_h = area.width, area.height
        target_w, target_h = _compute_target_dims(cur_w, cur_h, aw, ah, max_w, max_h)
        growth_w = target_w - cur_w
        growth_h = target_h - cur_h

        width_edge = _pick_width_edge(area, screen)
        height_edge = _pick_height_edge(area, screen)

        notes = []
        if growth_w == 0:
            notes.append("width unchanged")
        elif width_edge is None:
            notes.append("width pinned (no horizontal neighbour)")
        if growth_h == 0:
            notes.append("height unchanged")
        elif height_edge is None:
            notes.append("height pinned (no vertical neighbour)")

        # Defer the actual moves so cursor_warp can settle in Blender's input
        # pipeline before area_move reads it. Closure captures the area,
        # window, screen, edges, and growths.
        def _apply():
            try:
                if growth_w != 0 and width_edge is not None:
                    _move_edge(window, screen, area, width_edge, growth_w)
                if growth_h != 0 and height_edge is not None:
                    # Re-pick edge point because the area's geometry changed
                    # after the width move.
                    _move_edge(window, screen, area, height_edge, growth_h)
            except Exception as exc:
                log.exception("Deferred viewport reshape failed: %s", exc)
            return None

        bpy.app.timers.register(_apply, first_interval=0.02)

        msg_parts = [
            f"{label}: target {target_w}x{target_h} (was {cur_w}x{cur_h})"
        ]
        if growth_w != 0 and width_edge:
            msg_parts.append(f"width via {width_edge}")
        if growth_h != 0 and height_edge:
            msg_parts.append(f"height via {height_edge}")
        if notes:
            msg_parts.append("; ".join(notes))
        self.report({'INFO'}, " — ".join(msg_parts))
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# One-time cleanup of orphan No3D_PresetCamera left from earlier rev
# ---------------------------------------------------------------------------

def _cleanup_legacy_preset_camera_now():
    cam_name = "No3D_PresetCamera"
    try:
        obj = bpy.data.objects.get(cam_name)
        if obj is not None:
            scene = bpy.context.scene
            if scene and scene.camera is obj:
                scene.camera = None
            bpy.data.objects.remove(obj, do_unlink=True)
        cam_data = bpy.data.cameras.get(cam_name)
        if cam_data is not None and cam_data.users == 0:
            bpy.data.cameras.remove(cam_data)
    except Exception as exc:
        log.warning("Legacy preset-camera cleanup failed: %s", exc)
    return None


def cleanup_legacy_preset_camera():
    """Schedule cleanup outside the register-time _RestrictData window."""
    bpy.app.timers.register(_cleanup_legacy_preset_camera_now, first_interval=0.1)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_classes = (
    NO3D_OT_apply_viewport_preset,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    cleanup_legacy_preset_camera()


def unregister():
    for cls in reversed(_classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
