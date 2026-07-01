"""
Header screenshot operators — buttons that live in editor header bars and
capture the editor's own area (or a sub-region of it) as a clean PNG.

Two operators:

- ``NO3D_OT_header_area_screenshot`` — captures ``context.area`` whole.
  Identical output to the existing Editor Screenshot panel button, but no
  picker / no area_token: the header lives inside the area, so we already
  know which one we want.
- ``NO3D_OT_viewport_npanel_screenshot`` — captures the active View3D
  area, then crops to the ``'UI'`` (N-panel) region. Used from the
  View3D header to grab a clean shot of whatever the N-panel currently
  shows. Rounded corners disabled in v1 (the outer-corner logic is for
  full-area rects, not sub-rects — punted per spec).
"""

import logging

import bpy
from bpy.types import Operator

from . import editor_screenshot

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Whole-area screenshot from a header button
# ---------------------------------------------------------------------------

class NO3D_OT_header_area_screenshot(Operator):
    """Capture the editor area this header lives in as a clean PNG."""
    bl_idname = "no3d.header_area_screenshot"
    bl_label = "Capture Editor Area"
    bl_description = (
        "Screenshot the editor area this header belongs to "
        "(no chrome, no neighbours; saved PNG + clipboard)"
    )
    bl_options = {'REGISTER'}

    def execute(self, context):
        area = context.area
        window = context.window
        if area is None or window is None:
            self.report({'ERROR'}, "No area context")
            return {'CANCELLED'}

        round_corners, radius = editor_screenshot._read_capture_prefs(context)
        out_dir = editor_screenshot._resolve_output_dir(context)
        try:
            _path, msg = editor_screenshot._capture_area(
                window, area, out_dir, round_corners, radius,
            )
        except Exception as exc:
            log.exception("Header area screenshot failed")
            self.report({'ERROR'}, f"Capture failed: {exc}")
            return {'CANCELLED'}

        self.report({'INFO'}, msg)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# N-panel-only screenshot from the View3D header
# ---------------------------------------------------------------------------

def _find_ui_region(area):
    """Return the 'UI' (N-panel) region of `area`, or None if absent."""
    if area is None:
        return None
    for region in area.regions:
        if region.type == 'UI':
            return region
    return None


def _crop_array_to_region(arr, area, region):
    """Crop `arr` (a top-down RGBA array of the full area) to the pixel
    rect occupied by `region`. Region x/y are window-space; subtract area
    x/y to make them area-relative. arr's row 0 is the top of the area
    (top-down), but Blender's region.y is measured from the bottom — so
    flip vertically.
    """
    h, w = arr.shape[:2]

    rel_x = int(region.x - area.x)
    rel_y_bottom = int(region.y - area.y)
    rw = int(region.width)
    rh = int(region.height)

    # Convert bottom-origin region rect to top-down pixel rows.
    top = h - (rel_y_bottom + rh)
    bottom = h - rel_y_bottom
    left = rel_x
    right = rel_x + rw

    # Clamp to the array bounds; if the region overflows somehow, take the
    # intersection.
    top = max(0, min(h, top))
    bottom = max(0, min(h, bottom))
    left = max(0, min(w, left))
    right = max(0, min(w, right))

    if bottom <= top or right <= left:
        raise RuntimeError(
            f"N-panel region maps to empty rect "
            f"(area {area.width}x{area.height}, region "
            f"{rw}x{rh} @ {rel_x},{rel_y_bottom})"
        )

    return arr[top:bottom, left:right, :].copy()


class NO3D_OT_viewport_npanel_screenshot(Operator):
    """Capture the 3D Viewport's N-panel (UI region) as a clean PNG."""
    bl_idname = "no3d.viewport_npanel_screenshot"
    bl_label = "Capture N-Panel"
    bl_description = (
        "Screenshot just the 3D Viewport's N-panel column "
        "(saved PNG + clipboard). Requires the N-panel to be open"
    )
    bl_options = {'REGISTER'}

    def execute(self, context):
        area = context.area
        window = context.window
        if area is None or window is None or area.type != 'VIEW_3D':
            self.report({'ERROR'}, "Run from a 3D Viewport header")
            return {'CANCELLED'}

        region = _find_ui_region(area)
        if region is None or region.width == 0:
            self.report({'WARNING'}, "N-panel is not open")
            return {'CANCELLED'}

        try:
            arr = editor_screenshot._capture_area_to_array(window, area)
            cropped = _crop_array_to_region(arr, area, region)
        except Exception as exc:
            log.exception("N-panel screenshot capture failed")
            self.report({'ERROR'}, f"Capture failed: {exc}")
            return {'CANCELLED'}

        # Rounded corners on the N-panel sub-rect are punted for v1 —
        # _which_corners_outer is area-vs-window; sub-region geometry is
        # different and not worth the surface area right now.

        out_dir = editor_screenshot._resolve_output_dir(context)
        try:
            _path, msg = editor_screenshot._save_array_and_clipboard(
                cropped, out_dir, "view3d_npanel",
            )
        except Exception as exc:
            log.exception("N-panel screenshot save failed")
            self.report({'ERROR'}, f"Save failed: {exc}")
            return {'CANCELLED'}

        self.report({'INFO'}, msg)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_classes = (
    NO3D_OT_header_area_screenshot,
    NO3D_OT_viewport_npanel_screenshot,
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
