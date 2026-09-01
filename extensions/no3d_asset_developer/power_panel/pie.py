"""Power Panel radial overlay with click/gesture and number selection."""

import math

import blf
import bpy
import gpu
from bpy.props import IntProperty
from gpu_extras.batch import batch_for_shader

from . import activation, config, discovery, filter, slots


_addon_keymaps = []
_previous_by_area = {}
_last_previous = ""
_NUMBER_EVENTS = {
    "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5,
    "SIX": 6, "SEVEN": 7, "EIGHT": 8, "NINE": 9,
}
_OFFSETS = {
    "WEST": (-220, 0),
    "EAST": (220, 0),
    "SOUTH": (0, -125),
    "NORTH": (0, 125),
    "NORTHWEST": (-165, 100),
    "NORTHEAST": (165, 100),
    "SOUTHWEST": (-165, -100),
    "SOUTHEAST": (165, -100),
}


def _slot_categories(context=None):
    return {
        slot: category
        for slot, category in slots.slot_categories(context).items()
        if category
    }


def _destination_label(category):
    return config.DESTINATION_LABELS.get(category, category)


def _registered_categories():
    return discovery.registered_categories()


def _area_key(area):
    try:
        return area.as_pointer()
    except (AttributeError, ReferenceError):
        return id(area)


def _activate_category(context, canonical):
    global _last_previous
    region = discovery.sidebar_region(context.area)
    if region is None:
        return False, "No sidebar region exists in this 3D View"
    available = _registered_categories()
    displayed = slots.displayed_category(canonical, context)
    category = displayed if displayed in available else canonical
    if category not in available:
        return False, f"Sidebar category is unavailable: {canonical}"

    previous = getattr(region, "active_panel_category", "")
    if previous and previous != category:
        _previous_by_area[_area_key(context.area)] = previous
        _last_previous = previous
    filter.apply_filter("")
    if not activation.activate(context, category):
        return False, f"Could not activate sidebar category: {canonical}"
    return True, category


def _invoke_search():
    try:
        return bpy.ops.view3d.no3d_search_sidebar_tabs("INVOKE_DEFAULT")
    except RuntimeError:
        return {"CANCELLED"}


class NO3D_AD_OT_open_sidebar_slot(bpy.types.Operator):
    """Open the N-panel category assigned to a numbered Power Panel slot."""

    bl_idname = "view3d.no3d_open_sidebar_slot"
    bl_label = "Open Numbered Sidebar Tab"
    bl_options = {"INTERNAL"}

    slot: IntProperty(name="Slot", min=1, max=9)

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"

    def execute(self, context):
        canonical = _slot_categories(context).get(self.slot)
        if canonical is None:
            self.report({"WARNING"}, f"Power Panel slot {self.slot} is unassigned")
            _invoke_search()
            return {"CANCELLED"}
        ok, message = _activate_category(context, canonical)
        if not ok:
            self.report({"WARNING"}, message)
            _invoke_search()
            return {"CANCELLED"}
        return {"FINISHED"}


class NO3D_PP_OT_toggle_sidebar(bpy.types.Operator):
    bl_idname = "view3d.no3d_toggle_sidebar"
    bl_label = "Toggle Sidebar"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"

    def execute(self, context):
        context.space_data.show_region_ui = not context.space_data.show_region_ui
        context.area.tag_redraw()
        return {"FINISHED"}


class NO3D_PP_OT_previous_sidebar_tab(bpy.types.Operator):
    bl_idname = "view3d.no3d_previous_sidebar_tab"
    bl_label = "Last Used Sidebar Tab"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"

    def execute(self, context):
        target = _previous_by_area.get(_area_key(context.area), _last_previous)
        if not target:
            self.report({"WARNING"}, "No previous Power Panel tab is recorded")
            _invoke_search()
            return {"CANCELLED"}
        ok, message = _activate_category(context, slots.canonical_category(target))
        if not ok:
            self.report({"WARNING"}, message)
            _invoke_search()
            return {"CANCELLED"}
        return {"FINISHED"}


class VIEW3D_MT_no3d_sidebar_tabs_pie(bpy.types.Menu):
    """Native-menu fallback; Option+Tab uses the richer radial overlay."""

    bl_idname = "VIEW3D_MT_no3d_sidebar_tabs_pie"
    bl_label = "Power Panel"

    def draw(self, context):
        pie = self.layout.menu_pie()
        assignments = _slot_categories(context)
        for _direction, kind, slot, label in config.PIE_DIRECTIONS:
            if kind == "slot":
                operator = pie.operator(
                    NO3D_AD_OT_open_sidebar_slot.bl_idname,
                    text=f"{slot}  {assignments.get(slot, label)}",
                )
                operator.slot = slot
            elif kind == "search":
                pie.operator("view3d.no3d_search_sidebar_tabs", text=label, icon="VIEWZOOM")
            elif kind == "toggle":
                pie.operator(NO3D_PP_OT_toggle_sidebar.bl_idname, text=label, icon="MENU_PANEL")
            elif kind == "previous":
                pie.operator(NO3D_PP_OT_previous_sidebar_tab.bl_idname, text=label, icon="BACK")


class NO3D_PP_OT_invoke_navigation(bpy.types.Operator):
    """Open the Power Panel radial selector."""

    bl_idname = "view3d.no3d_power_panel"
    bl_label = "Power Panel"
    bl_description = "Open Power Panel; click, gesture, or press a displayed number"
    bl_options = {"INTERNAL"}

    _handler = None
    _items = None
    _hover = -1
    _center = (0, 0)

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"

    def _build_items(self, context):
        assignments = _slot_categories(context)
        result = []
        for direction, kind, slot, label in config.PIE_DIRECTIONS:
            visible = (
                f"{slot}  {_destination_label(assignments.get(slot, label))}"
                if kind == "slot" else label
            )
            result.append({
                "direction": direction,
                "kind": kind,
                "slot": slot,
                "label": visible,
            })
        return result

    def invoke(self, context, event):
        width, height = context.region.width, context.region.height
        self._center = (
            max(250, min(width - 250, event.mouse_region_x)),
            max(145, min(height - 145, event.mouse_region_y)),
        )
        self._items = self._build_items(context)
        self._hover = -1
        self._handler = bpy.types.SpaceView3D.draw_handler_add(
            self._draw, (), "WINDOW", "POST_PIXEL"
        )
        context.window_manager.modal_handler_add(self)
        context.workspace.status_text_set(
            "Power Panel: click/gesture or press 1-9 | Esc cancels"
        )
        context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def _cleanup(self, context):
        if self._handler is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handler, "WINDOW")
            self._handler = None
        context.workspace.status_text_set(None)
        context.area.tag_redraw()

    def _item_center(self, item):
        dx, dy = _OFFSETS[item["direction"]]
        return self._center[0] + dx, self._center[1] + dy

    def _update_hover(self, x, y):
        distance = math.hypot(x - self._center[0], y - self._center[1])
        if distance < 38:
            self._hover = -1
            return
        self._hover = min(
            range(len(self._items)),
            key=lambda index: math.hypot(
                x - self._item_center(self._items[index])[0],
                y - self._item_center(self._items[index])[1],
            ),
        )

    @staticmethod
    def _rect(shader, x, y, width, height, color):
        vertices = ((x, y), (x + width, y), (x + width, y + height), (x, y + height))
        batch = batch_for_shader(shader, "TRI_FAN", {"pos": vertices})
        shader.bind()
        shader.uniform_float("color", color)
        batch.draw(shader)

    def _draw(self):
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        gpu.state.blend_set("ALPHA")
        for index, item in enumerate(self._items):
            cx, cy = self._item_center(item)
            label = item["label"]
            blf.size(0, 14)
            text_width, text_height = blf.dimensions(0, label)
            width = max(126, text_width + 28)
            height = 34
            color = (0.12, 0.38, 0.85, 0.96) if index == self._hover else (0.055, 0.055, 0.065, 0.92)
            self._rect(shader, cx - width / 2, cy - height / 2, width, height, color)
            blf.color(0, 1.0, 1.0, 1.0, 1.0)
            blf.position(0, cx - text_width / 2, cy - text_height / 2, 0)
            blf.draw(0, label)
        gpu.state.blend_set("NONE")

    def _execute_item(self, context, item):
        kind = item["kind"]
        if kind == "slot":
            return bpy.ops.view3d.no3d_open_sidebar_slot(slot=item["slot"])
        if kind == "search":
            return _invoke_search()
        if kind == "toggle":
            return bpy.ops.view3d.no3d_toggle_sidebar()
        if kind == "previous":
            return bpy.ops.view3d.no3d_previous_sidebar_tab()
        return {"CANCELLED"}

    def _select_slot(self, context, slot):
        print(f"POWER_PANEL_NUMBER_OK slot={slot}")
        self._cleanup(context)
        return bpy.ops.view3d.no3d_open_sidebar_slot(slot=slot)

    def modal(self, context, event):
        if event.type == "MOUSEMOVE":
            self._update_hover(event.mouse_region_x, event.mouse_region_y)
            context.area.tag_redraw()
            return {"RUNNING_MODAL"}
        if event.value == "PRESS" and event.type in _NUMBER_EVENTS and not any(
            (event.ctrl, event.shift, event.alt, event.oskey)
        ):
            slot = _NUMBER_EVENTS[event.type]
            return self._select_slot(context, slot)
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            if self._hover >= 0:
                item = self._items[self._hover]
                self._cleanup(context)
                return self._execute_item(context, item)
            return {"RUNNING_MODAL"}
        if event.type in {"ESC", "RIGHTMOUSE"}:
            self._cleanup(context)
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}

    def cancel(self, context):
        self._cleanup(context)


_CLASSES = (
    NO3D_AD_OT_open_sidebar_slot,
    NO3D_PP_OT_toggle_sidebar,
    NO3D_PP_OT_previous_sidebar_tab,
    VIEW3D_MT_no3d_sidebar_tabs_pie,
    NO3D_PP_OT_invoke_navigation,
)


def _register_keymap():
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig is None:
        return
    keymap = keyconfig.keymaps.new(name="3D View", space_type="VIEW_3D")
    # Live extension reloads replace this module and lose the old Python-side
    # handle list. Remove semantic duplicates from the add-on keyconfig before
    # creating the one owned binding.
    for old_item in tuple(keymap.keymap_items):
        if old_item.idname == NO3D_PP_OT_invoke_navigation.bl_idname:
            keymap.keymap_items.remove(old_item)
    item = keymap.keymap_items.new(
        NO3D_PP_OT_invoke_navigation.bl_idname,
        type="TAB",
        value="PRESS",
        alt=True,
    )
    _addon_keymaps.append((keymap, item))


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def _unregister_keymap():
    for keymap, item in _addon_keymaps:
        try:
            keymap.keymap_items.remove(item)
        except (ReferenceError, RuntimeError):
            pass
    _addon_keymaps.clear()


def unregister():
    _unregister_keymap()
    _previous_by_area.clear()
    global _last_previous
    _last_previous = ""
    for cls in reversed(_CLASSES):
        if cls.is_registered:
            bpy.utils.unregister_class(cls)
