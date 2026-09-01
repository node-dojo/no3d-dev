"""Power Panel — No3d Dev's complete 3D View sidebar navigation suite."""

import bpy
from bpy.app.handlers import persistent

from . import activation, filter, keymaps, order, pie, preferences, router, search, slots


def reconcile():
    """Restore and deterministically rebuild the configured sidebar state."""
    filter.apply_filter("")
    activation.unregister()
    slots.restore_numbering()
    router.restore_routes()
    routed = router.apply_routes()
    numbered = slots.apply_numbering()
    ordered = order.apply_npanel_order()
    print(
        "POWER_PANEL_OK "
        f"routed={bool(routed)} numbered={bool(numbered)} ordered={bool(ordered)}"
    )
    return bool(routed and numbered)


def _deferred_reconcile():
    reconcile()
    return None


def schedule_reconcile(delay=1.0):
    if bpy.app.timers.is_registered(_deferred_reconcile):
        bpy.app.timers.unregister(_deferred_reconcile)
    bpy.app.timers.register(_deferred_reconcile, first_interval=delay)


@persistent
def _load_post_reconcile(_unused):
    schedule_reconcile(1.0)


def install_preference_properties(preferences_class):
    preferences.install_properties(preferences_class)


def draw_preferences(layout, addon_preferences):
    preferences.draw(layout, addon_preferences)


def keymap_groups():
    return keymaps.groups()


def register():
    search.register()
    filter.register()
    slots.register()
    pie.register()
    order.register()
    keymaps.register()
    if _load_post_reconcile not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_load_post_reconcile)
    schedule_reconcile(1.0)


def unregister():
    if bpy.app.timers.is_registered(_deferred_reconcile):
        bpy.app.timers.unregister(_deferred_reconcile)
    if _load_post_reconcile in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_post_reconcile)
    filter.apply_filter("")
    activation.unregister()
    keymaps.unregister()
    order.unregister()
    pie.unregister()
    slots.unregister()
    filter.unregister()
    search.unregister()
    router.restore_routes()
