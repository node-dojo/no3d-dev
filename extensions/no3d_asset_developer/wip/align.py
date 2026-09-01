"""View Align — align selected geometry or objects to a view-relative direction.

The pie's directional slots map screen directions (left/right/top/bottom) to
whichever world axis currently points that way on screen, so "Right" always
flattens things toward the right of the viewport regardless of orbit.

Edit mode: aligns selected verts (works in world space, writes back to local).
Object mode: aligns selected object origins along the resolved axis.

Self-contained: depends only on bpy/bmesh. Exposes CLASSES plus
register_keymap()/unregister_keymap() hooks called by __init__.
"""

import math

import blf
import bmesh
import bpy
import gpu
from bpy.props import EnumProperty
from bpy.types import Menu, Operator
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
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


class NO3D_WIP_OT_view_distribute(Operator):
    """Interactively stack object bounds along the world axis nearest the drag."""

    bl_idname = ids.VIEW_DISTRIBUTE_OT_IDNAME
    bl_label = ids.VIEW_DISTRIBUTE_OT_LABEL
    bl_description = "Stack selected object bounds in a view-relative direction, then drag to set the gap"
    bl_options = {"REGISTER", "UNDO", "BLOCKING"}

    _world_axes = (
        Vector((1.0, 0.0, 0.0)),
        Vector((0.0, 1.0, 0.0)),
        Vector((0.0, 0.0, 1.0)),
    )

    @classmethod
    def poll(cls, context):
        return (
            context.mode == "OBJECT"
            and context.area is not None
            and context.area.type == "VIEW_3D"
            and len(context.selected_objects) >= 2
        )

    @staticmethod
    def _object_bounds(obj):
        corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
        return tuple(
            (min(point[axis] for point in corners), max(point[axis] for point in corners))
            for axis in range(3)
        )

    def _capture_view(self, context):
        rotation = context.space_data.region_3d.view_rotation.copy()
        view_right = rotation @ Vector((1.0, 0.0, 0.0))
        view_up = rotation @ Vector((0.0, 1.0, 0.0))
        self._axis_screen = []
        for world_axis in self._world_axes:
            projected = Vector((world_axis.dot(view_right), world_axis.dot(view_up)))
            length = projected.length
            self._axis_screen.append(projected / length if length > 1.0e-5 else None)

        # Initial direction is whichever visible world axis most closely follows
        # screen-horizontal, ordered toward screen-right.
        candidates = [
            (abs(projected.x), axis)
            for axis, projected in enumerate(self._axis_screen)
            if projected is not None
        ]
        self._axis = max(candidates)[1]
        self._forward = self._axis_screen[self._axis].x >= 0.0

    def _pick_direction(self, delta):
        if delta.length < 4.0:
            return
        direction = delta.normalized()
        candidates = [
            (abs(direction.dot(projected)), axis)
            for axis, projected in enumerate(self._axis_screen)
            if projected is not None
        ]
        _score, self._axis = max(candidates)
        self._forward = direction.dot(self._axis_screen[self._axis]) >= 0.0

    def _mouse_world_distance(self, context, mouse):
        start = view3d_utils.region_2d_to_location_3d(
            context.region,
            context.space_data.region_3d,
            self._start_mouse,
            self._anchor_world,
        )
        current = view3d_utils.region_2d_to_location_3d(
            context.region,
            context.space_data.region_3d,
            mouse,
            self._anchor_world,
        )
        return (current - start).length

    @staticmethod
    def _snap_increment(scene):
        scale = scene.unit_settings.scale_length or 1.0
        # One centimetre in the scene's displayed unit scale.
        return 0.01 / scale

    def _update_from_event(self, context, event):
        self._mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        delta = self._mouse - self._start_mouse
        self._pick_direction(delta)

        if self._zero_gap:
            gap = 0.0
        else:
            gap = self._mouse_world_distance(context, self._mouse)
            if event.shift:
                gap *= 0.1
            if event.ctrl:
                increment = self._snap_increment(context.scene)
                gap = round(gap / increment) * increment
            if event.alt:
                gap = -gap
        self._gap = gap
        self._apply_distribution()

    def _apply_distribution(self):
        for obj in self._objects:
            obj.matrix_world = self._original_matrices[obj].copy()

        axis = self._axis
        ordered = sorted(
            self._objects,
            key=lambda obj: sum(self._bounds[obj][axis]) * 0.5,
            reverse=not self._forward,
        )
        previous = ordered[0]
        previous_offset = 0.0
        for obj in ordered[1:]:
            obj_min, obj_max = self._bounds[obj][axis]
            prev_min, prev_max = self._bounds[previous][axis]
            if self._forward:
                previous_edge = prev_max + previous_offset
                offset = previous_edge + self._gap - obj_min
            else:
                previous_edge = prev_min + previous_offset
                offset = previous_edge - self._gap - obj_max
            matrix = self._original_matrices[obj].copy()
            matrix.translation[axis] += offset
            obj.matrix_world = matrix
            previous = obj
            previous_offset = offset

        self._ordered = ordered

    def _formatted_gap(self):
        settings = self._scene.unit_settings
        value = self._gap * (settings.scale_length or 1.0)
        if settings.system == "NONE":
            return f"{self._gap:.4g} BU"
        return bpy.utils.units.to_string(
            settings.system,
            "LENGTH",
            value,
            precision=4,
            split_unit=False,
        )

    def _draw_guide(self):
        if not self._ordered or self._area != bpy.context.area:
            return
        region = bpy.context.region
        rv3d = getattr(bpy.context.space_data, "region_3d", None)
        if region is None or rv3d is None:
            return

        centers = []
        for obj in self._ordered:
            corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
            centers.append(sum(corners, Vector()) / 8.0)
        projected = [view3d_utils.location_3d_to_region_2d(region, rv3d, point) for point in centers]
        projected = [point for point in projected if point is not None]
        if len(projected) >= 2:
            shader = gpu.shader.from_builtin("UNIFORM_COLOR")
            batch = batch_for_shader(shader, "LINE_STRIP", {"pos": projected})
            gpu.state.blend_set("ALPHA")
            gpu.state.line_width_set(2.0)
            shader.bind()
            shader.uniform_float("color", (0.35, 0.8, 1.0, 0.8))
            batch.draw(shader)

            # Short perpendicular ticks mark each object's live min/max bound
            # along the chosen axis, making positive and negative gaps legible.
            screen_axis = self._axis_screen[self._axis]
            perpendicular = Vector((-screen_axis.y, screen_axis.x)) * 4.0
            tick_vertices = []
            for obj in self._ordered:
                bounds = self._object_bounds(obj)
                center = Vector(tuple(sum(bounds[i]) * 0.5 for i in range(3)))
                for edge in bounds[self._axis]:
                    point = center.copy()
                    point[self._axis] = edge
                    point_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, point)
                    if point_2d is not None:
                        tick_vertices.extend((point_2d - perpendicular, point_2d + perpendicular))
            if tick_vertices:
                tick_batch = batch_for_shader(shader, "LINES", {"pos": tick_vertices})
                tick_batch.draw(shader)
            gpu.state.line_width_set(1.0)
            gpu.state.blend_set("NONE")

        axis_name = "XYZ"[self._axis]
        arrow = "→" if self._forward else "←"
        title = f"{axis_name} {arrow}   Gap {self._formatted_gap()}"
        if self._zero_gap:
            title += "   ZERO LOCK"
        help_text = "Z Zero Gap  ·  Shift Fine  ·  Ctrl Snap  ·  Alt Overlap"
        x, y = self._mouse.x + 18.0, self._mouse.y + 22.0
        font_id = 0
        blf.size(font_id, 13)
        title_w, title_h = blf.dimensions(font_id, title)
        blf.size(font_id, 11)
        help_w, help_h = blf.dimensions(font_id, help_text)
        width = max(title_w, help_w) + 20.0
        height = title_h + help_h + 24.0

        vertices = (
            (x, y), (x + width, y), (x + width, y + height),
            (x, y), (x + width, y + height), (x, y + height),
        )
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        background = batch_for_shader(shader, "TRIS", {"pos": vertices})
        gpu.state.blend_set("ALPHA")
        shader.bind()
        shader.uniform_float("color", (0.055, 0.065, 0.08, 0.92))
        background.draw(shader)

        blf.size(font_id, 13)
        blf.color(font_id, 0.72, 0.9, 1.0, 1.0)
        blf.position(font_id, x + 10.0, y + height - 20.0, 0)
        blf.draw(font_id, title)
        blf.size(font_id, 11)
        blf.color(font_id, 0.68, 0.7, 0.74, 1.0)
        blf.position(font_id, x + 10.0, y + 8.0, 0)
        blf.draw(font_id, help_text)
        gpu.state.blend_set("NONE")

    def _finish(self, context):
        if self._draw_handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._draw_handle, "WINDOW")
            self._draw_handle = None
        context.area.header_text_set(None)
        context.window.cursor_modal_restore()
        context.area.tag_redraw()

    def invoke(self, context, event):
        self._objects = list(context.selected_objects)
        self._original_matrices = {obj: obj.matrix_world.copy() for obj in self._objects}
        self._bounds = {obj: self._object_bounds(obj) for obj in self._objects}
        all_centers = [
            Vector(tuple(sum(bounds[axis]) * 0.5 for axis in range(3)))
            for bounds in self._bounds.values()
        ]
        self._anchor_world = sum(all_centers, Vector()) / len(all_centers)
        self._start_mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self._mouse = self._start_mouse.copy()
        self._gap = 0.0
        self._zero_gap = False
        self._ordered = []
        self._draw_handle = None
        self._scene = context.scene
        self._area = context.area
        self._capture_view(context)
        self._apply_distribution()

        self._draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_guide, (), "WINDOW", "POST_PIXEL"
        )
        context.window.cursor_modal_set("CROSSHAIR")
        context.area.header_text_set(
            "View Distribute: move to choose direction/gap · Z zero gap · LMB/Enter confirm · RMB/Esc cancel"
        )
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            for obj in self._objects:
                obj.matrix_world = self._original_matrices[obj].copy()
            self._finish(context)
            return {"CANCELLED"}
        if event.type in {"LEFTMOUSE", "RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            self._finish(context)
            return {"FINISHED"}
        if event.type == "Z" and event.value == "PRESS":
            self._zero_gap = not self._zero_gap
            self._update_from_event(context, event)
        elif event.type == "MOUSEMOVE" or event.type in {
            "LEFT_SHIFT", "RIGHT_SHIFT", "LEFT_CTRL", "RIGHT_CTRL", "LEFT_ALT", "RIGHT_ALT"
        }:
            self._update_from_event(context, event)
        context.area.tag_redraw()
        return {"RUNNING_MODAL"}


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
        pie.operator(ids.VIEW_DISTRIBUTE_OT_IDNAME, text="Distribute", icon="ALIGN_JUSTIFY")  # NW
        pie.separator()  # NE
        pie.separator()  # SW
        pie.operator(ids.VIEW_ALIGN_OT_IDNAME, text="Center").direction = ids.DIR_CENTER  # SE


CLASSES = (
    NO3D_WIP_OT_view_align,
    NO3D_WIP_OT_view_distribute,
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
