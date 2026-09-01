"""Search and activate 3D View sidebar categories."""

import bpy
from bpy.props import EnumProperty

from . import activation, discovery


_addon_keymaps = []
_displaced_f5_items = []
_enum_items_cache = []


def _panel_types():
    """Yield all registered 3D View sidebar panels, including dynamic classes."""
    yield from discovery.panel_types()


def _category_items(_operator, context):
    """Return categories usable in the invoking 3D View context."""
    global _enum_items_cache
    categories = {}
    for panel_type in _panel_types():
        category = getattr(panel_type, "bl_category", "")
        if not category:
            continue
        try:
            if not panel_type.poll(context):
                continue
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            # A third-party poll failure should not make its category
            # unreachable through the switcher.
            pass
        categories.setdefault(category, set()).add(
            getattr(panel_type, "bl_label", panel_type.__name__)
        )

    _enum_items_cache = [
        (
            category,
            category,
            "Panels: " + ", ".join(sorted(labels, key=str.casefold)),
        )
        for category, labels in sorted(categories.items(), key=lambda item: item[0].casefold())
    ]
    return _enum_items_cache


def _sidebar_region(area):
    return discovery.sidebar_region(area)


class NO3D_AD_OT_search_sidebar_tabs(bpy.types.Operator):
    """Search the available N-panel categories and activate one."""

    bl_idname = "view3d.no3d_search_sidebar_tabs"
    bl_label = "Search Sidebar Tabs"
    bl_description = "Type to find and activate a 3D View sidebar tab"
    bl_options = {"REGISTER"}
    bl_property = "category"

    category: EnumProperty(name="Sidebar Tab", items=_category_items)

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"

    def invoke(self, context, _event):
        items = _category_items(self, context)
        if not items:
            self.report({"WARNING"}, "No sidebar tabs are available in this context")
            return {"CANCELLED"}

        region = _sidebar_region(context.area)
        active = getattr(region, "active_panel_category", "") if region else ""
        identifiers = {item[0] for item in items}
        self.category = active if active in identifiers else items[0][0]
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        region = _sidebar_region(context.area)
        if region is None:
            self.report({"ERROR"}, "No sidebar region exists in this 3D View")
            return {"CANCELLED"}

        context.space_data.show_region_ui = True
        if not activation.activate(context, self.category):
            self.report({"ERROR"}, "Sidebar tab is unavailable")
            return {"CANCELLED"}

        context.area.tag_redraw()
        return {"FINISHED"}


_CLASSES = (NO3D_AD_OT_search_sidebar_tabs,)


def _is_plain_f5(item):
    return (
        item.type == "F5"
        and item.value == "PRESS"
        and not item.shift
        and not item.ctrl
        and not item.alt
        and not item.oskey
        and item.idname != "view3d.no3d_type_sidebar_tab_filter"
    )


def _register_keymap():
    wm = bpy.context.window_manager
    addon_config = wm.keyconfigs.addon
    if addon_config is None:
        return

    # F5 was explicitly reassigned from the user's unused Quick Save action.
    # Disable exact plain-F5 conflicts at runtime and restore them if this
    # extension is disabled; modified F5 gestures remain untouched.
    for keyconfig in (wm.keyconfigs.user, wm.keyconfigs.addon):
        if keyconfig is None:
            continue
        for keymap in keyconfig.keymaps:
            if keymap.space_type not in {"EMPTY", "VIEW_3D"}:
                continue
            for item in keymap.keymap_items:
                if item.active and _is_plain_f5(item):
                    item.active = False
                    _displaced_f5_items.append(item)

    keymap = addon_config.keymaps.new(name="3D View", space_type="VIEW_3D")
    # A prior live-reloaded module may no longer hold the Python references
    # required by its normal unregister path. Keep the add-on keyconfig
    # idempotent by operator identity.
    for old_item in tuple(keymap.keymap_items):
        if old_item.idname == "view3d.no3d_type_sidebar_tab_filter":
            keymap.keymap_items.remove(old_item)
    item = keymap.keymap_items.new(
        "view3d.no3d_type_sidebar_tab_filter",
        type="F5",
        value="PRESS",
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

    for item in _displaced_f5_items:
        try:
            item.active = True
        except (ReferenceError, RuntimeError):
            pass
    _displaced_f5_items.clear()


def unregister():
    _unregister_keymap()

    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
