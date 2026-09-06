"""Native Blender Power Panel pie navigation."""

import bpy
from bpy.props import IntProperty

from . import activation, config, discovery, filter, slots


_addon_keymaps = []
_previous_by_area = {}
_last_previous = ""
def _slot_categories(context=None):
    return {
        slot: category
        for slot, category in slots.slot_categories(context).items()
        if category
    }


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
    """Native Power Panel pie, selectable by gesture, click, or number."""

    bl_idname = "VIEW3D_MT_no3d_sidebar_tabs_pie"
    bl_label = "Power Panel"

    def draw(self, context):
        pie = self.layout.menu_pie()
        assignments = _slot_categories(context)
        for number, (_direction, kind, slot, label) in enumerate(
            config.PIE_DIRECTIONS, start=1
        ):
            if kind == "slot":
                operator = pie.operator(
                    NO3D_AD_OT_open_sidebar_slot.bl_idname,
                    text=f"{slot}  {assignments.get(slot, label)}",
                )
                operator.slot = slot
            elif kind == "search":
                pie.operator(
                    "view3d.no3d_search_sidebar_tabs",
                    text=f"{number}  {label}",
                    icon="VIEWZOOM",
                )
            elif kind == "toggle":
                pie.operator(
                    NO3D_PP_OT_toggle_sidebar.bl_idname,
                    text=f"{number}  {label}",
                    icon="MENU_PANEL",
                )
            elif kind == "previous":
                pie.operator(
                    NO3D_PP_OT_previous_sidebar_tab.bl_idname,
                    text=f"{number}  {label}",
                    icon="BACK",
                )


class NO3D_PP_OT_invoke_navigation(bpy.types.Operator):
    """Open the native Blender Power Panel pie."""

    bl_idname = "view3d.no3d_power_panel"
    bl_label = "Power Panel"
    bl_description = "Open Power Panel; click, gesture, or press 1-8"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"

    def invoke(self, context, event):
        return bpy.ops.wm.call_menu_pie(
            "INVOKE_DEFAULT",
            name=VIEW3D_MT_no3d_sidebar_tabs_pie.bl_idname,
        )


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
    # creating the one owned binding. Also remove the superseded custom-modal
    # operator binding from pre-native Power Panel builds.
    for old_item in tuple(keymap.keymap_items):
        is_owned_native_pie = (
            old_item.idname == "wm.call_menu_pie"
            and getattr(old_item.properties, "name", "")
            == VIEW3D_MT_no3d_sidebar_tabs_pie.bl_idname
        )
        if old_item.idname == NO3D_PP_OT_invoke_navigation.bl_idname or is_owned_native_pie:
            keymap.keymap_items.remove(old_item)
    item = keymap.keymap_items.new(
        "wm.call_menu_pie",
        type="TAB",
        value="PRESS",
        alt=True,
    )
    item.properties.name = VIEW3D_MT_no3d_sidebar_tabs_pie.bl_idname
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
