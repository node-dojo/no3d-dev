"""Stable visible slot numbers and assignment lookup for Power Panel."""

import re
import bpy

from . import config, discovery

SLOT_LABELS = {
    category: f"[{slot}] {category}"
    for slot, category in config.DEFAULT_SLOTS.items()
    if category
}

CANONICAL_ALIASES = {
    "No3D Dev": "NO3D Dev",
}

_original_categories = {}


def panel_types(registered_only=True):
    return discovery.panel_types(registered_only)


def _depth(panel_type, by_idname):
    return discovery.depth(panel_type, by_idname)


def _reregister(panels, mutate):
    return discovery.reregister(panels, mutate, "Power Panel Slots")


def slot_categories(context=None):
    result = dict(config.DEFAULT_SLOTS)
    context = context or bpy.context
    package = __package__.split(".power_panel", 1)[0]
    addon = context.preferences.addons.get(package)
    prefs = getattr(addon, "preferences", None) if addon else None
    if prefs is None:
        return result
    for slot in range(1, 10):
        prop = f"{config.SLOT_PROPERTY_PREFIX}{slot}"
        value = getattr(prefs, prop, result[slot])
        result[slot] = "" if value == "NONE" else value
    return result


def category_slots(context=None):
    result = {}
    for slot, category in slot_categories(context).items():
        if category and category not in result:
            result[category] = slot
    return result


def canonical_category(category):
    match = re.match(r"^\[(\d+)\]\s+(.*)$", category)
    if match:
        return match.group(2)
    return CANONICAL_ALIASES.get(category, category)


def displayed_category(category, context=None):
    canonical = canonical_category(category)
    slot = category_slots(context).get(canonical)
    return f"[{slot}] {canonical}" if slot else canonical


def apply_numbering():
    panels = []
    desired_categories = {}
    for panel in panel_types():
        category = getattr(panel, "bl_category", "")
        # One-time migration for long-running Blender processes that still
        # hold the Agent Bridge class mutated by No3d Dev 4.4.1. Its source
        # default is Agent; do not preserve the stale merged category.
        if (
            panel.__name__ == "AGENT_BRIDGE_PT_panel"
            and category in {"NO3D Dev", "[1] NO3D Dev"}
        ):
            _original_categories.setdefault(panel, "Agent")
            desired_categories[panel] = "Agent"
            panels.append(panel)
            continue
        displayed = displayed_category(category)
        if not category or displayed == category:
            continue
        _original_categories.setdefault(panel, category)
        desired_categories[panel] = displayed
        panels.append(panel)

    if not panels:
        return True

    def mutate(removed):
        for panel in removed:
            panel.bl_category = desired_categories[panel]

    result = _reregister(panels, mutate)
    print("NO3D_NUMBERED_TABS_OK")
    return result


def restore_numbering():
    panels = [panel for panel in _original_categories if panel.is_registered]
    if not panels:
        _original_categories.clear()
        return True

    def mutate(removed):
        for panel in removed:
            panel.bl_category = _original_categories.get(panel, panel.bl_category)

    result = _reregister(panels, mutate)
    _original_categories.clear()
    return result


def register():
    pass


def unregister():
    restore_numbering()
