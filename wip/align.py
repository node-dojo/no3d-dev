"""View Align — align selected geometry or objects to a view-relative direction.

The pie's directional slots map screen directions (left/right/top/bottom) to
whichever world axis currently points that way on screen, so "Right" always
flattens things toward the right of the viewport regardless of orbit.

Edit mode: aligns selected verts (works in world space, writes back to local).
Object mode: aligns selected object origins along the resolved axis.

Self-contained: depends only on bpy/bmesh. Exposes CLASSES plus
register_keymap()/unregister_keymap() hooks called by __init__.
"""

import bmesh
import bpy
from bpy.props import EnumProperty
from bpy.types import Menu, Operator
from mathutils import Vector

from . import ids

_DIRECTION_ITEMS = (
    (ids.DIR_LEFT, "Left", "Align to the left of the view"),
    (ids.DIR_RIGHT, "Right", "Align to the right of the view"),
    (ids.DIR_TOP, "Top", "Align to the top of the view"),
    (ids.DIR_BOTTOM, "Bottom", "Align to the bottom of the view"),
    (ids.DIR_CENTER, "Center", "Center on the view axes"),
)


def _get_right_and_up_axes(context):
    """Resolve which world axis points right/up on screen for the current view.

    Returns (right_idx, up_idx, flip_right, flip_up) where idx is 0/1/2 for X/Y/Z
    and the flip flags are True when the world axis points opposite to screen
    right / up.
    """
    r3d = context.space_data.region_3d
    view_right = r3d.view_rotation @ Vector((1, 0, 0))
    view_up = r3d.view_rotation @ Vector((0, 1, 0))

    world_axes = (Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))
    right = max(((view_right.dot(a), i) for i, a in enumerate(world_axes)), key=lambda x: abs(x[0]))
    up = max(((view_up.dot(a), i) for i, a in enumerate(world_axes)), key=lambda x: abs(x[0]))

    return right[1], up[1], right[0] < 0, up[0] < 0


class NO3D_WIP_OT_view_align(Operator):
    bl_idname = ids.VIEW_ALIGN_OT_IDNAME
    bl_label = ids.VIEW_ALIGN_OT_LABEL
    bl_description = "Align selected verts (edit) or objects (object) to the view-relative direction"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(name="Direction", items=_DIRECTION_ITEMS, default=ids.DIR_LEFT)

    @classmethod
    def poll(cls, context):
        if context.mode == "EDIT_MESH":
            return context.active_object is not None
        return len(context.selected_objects) > 0

    def execute(self, context):
        right_i, up_i, flip_r, flip_u = _get_right_and_up_axes(context)
        axes_types = self._resolve_axes_types(right_i, up_i, flip_r, flip_u)

        if context.mode == "EDIT_MESH":
            self._align_verts(context, axes_types)
        else:
            self._align_objects(context, axes_types)
        return {"FINISHED"}

    def _resolve_axes_types(self, right_i, up_i, flip_r, flip_u):
        """Map the chosen direction to a list of (axis_index, MIN/MAX/CENTER)."""
        if self.direction == ids.DIR_CENTER:
            return [(right_i, "CENTER"), (up_i, "CENTER")]

        if self.direction in (ids.DIR_LEFT, ids.DIR_RIGHT):
            axis = right_i
            if self.direction == ids.DIR_RIGHT:
                kind = "MIN" if flip_r else "MAX"
            else:
                kind = "MAX" if flip_r else "MIN"
        else:  # TOP / BOTTOM
            axis = up_i
            if self.direction == ids.DIR_TOP:
                kind = "MIN" if flip_u else "MAX"
            else:
                kind = "MAX" if flip_u else "MIN"
        return [(axis, kind)]

    @staticmethod
    def _target(coords, kind):
        if kind == "MIN":
            return min(coords)
        if kind == "MAX":
            return max(coords)
        return (min(coords) + max(coords)) / 2  # CENTER

    def _align_verts(self, context, axes_types):
        obj = context.active_object
        bm = bmesh.from_edit_mesh(obj.data)
        verts = [v for v in bm.verts if v.select]
        if not verts:
            self.report({"WARNING"}, "No vertices selected")
            return

        mw = obj.matrix_world
        mwi = mw.inverted_safe()
        world = [mw @ v.co for v in verts]
        for axis, kind in axes_types:
            target = self._target([c[axis] for c in world], kind)
            for c in world:
                c[axis] = target
        for v, c in zip(verts, world):
            v.co = mwi @ c
        bmesh.update_edit_mesh(obj.data)

    def _align_objects(self, context, axes_types):
        objs = context.selected_objects
        locs = [o.matrix_world.translation for o in objs]
        for axis, kind in axes_types:
            target = self._target([loc[axis] for loc in locs], kind)
            for o in objs:
                o.matrix_world.translation[axis] = target


class NO3D_WIP_MT_view_align_pie(Menu):
    bl_idname = ids.VIEW_ALIGN_PIE_IDNAME
    bl_label = ids.VIEW_ALIGN_PIE_LABEL

    def draw(self, context):
        pie = self.layout.menu_pie()
        # Pie slot order: W, E, S, N, NW, NE, SW, SE
        pie.operator(ids.VIEW_ALIGN_OT_IDNAME, text="Left").direction = ids.DIR_LEFT      # W
        pie.operator(ids.VIEW_ALIGN_OT_IDNAME, text="Right").direction = ids.DIR_RIGHT    # E
        pie.operator(ids.VIEW_ALIGN_OT_IDNAME, text="Bottom").direction = ids.DIR_BOTTOM  # S
        pie.operator(ids.VIEW_ALIGN_OT_IDNAME, text="Top").direction = ids.DIR_TOP        # N
        pie.separator()  # NW
        pie.separator()  # NE
        pie.separator()  # SW
        pie.operator(ids.VIEW_ALIGN_OT_IDNAME, text="Center").direction = ids.DIR_CENTER  # SE


CLASSES = (
    NO3D_WIP_OT_view_align,
    NO3D_WIP_MT_view_align_pie,
)

# Keymap entries live outside CLASSES (they aren't registerable types); __init__
# calls register_keymap()/unregister_keymap() when a section defines them.
_addon_keymaps = []

# (keymap name, space_type) pairs the pie should answer Alt+A in.
_KEYMAP_CONTEXTS = (
    ("3D View", "VIEW_3D"),
    ("Object Mode", "EMPTY"),
)


def register_keymap():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc is None:
        return
    for name, space_type in _KEYMAP_CONTEXTS:
        km = kc.keymaps.get(name) or kc.keymaps.new(name=name, space_type=space_type)
        kmi = km.keymap_items.new("wm.call_menu_pie", "A", "PRESS", alt=True)
        kmi.properties.name = ids.VIEW_ALIGN_PIE_IDNAME
        _addon_keymaps.append((km, kmi))


def unregister_keymap():
    for km, kmi in _addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except (RuntimeError, ReferenceError):
            pass
    _addon_keymaps.clear()
