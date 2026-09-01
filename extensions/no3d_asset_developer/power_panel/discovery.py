"""Shared registered-panel discovery and safe mutation utilities."""

import bpy


def panel_types(registered_only=True):
    seen = set()
    stack = list(bpy.types.Panel.__subclasses__())
    panels = []
    while stack:
        panel = stack.pop()
        if panel in seen:
            continue
        seen.add(panel)
        try:
            stack.extend(panel.__subclasses__())
            if registered_only and not panel.is_registered:
                continue
            if getattr(panel, "bl_space_type", None) != "VIEW_3D":
                continue
            if getattr(panel, "bl_region_type", None) != "UI":
                continue
        except (ReferenceError, TypeError):
            continue
        panels.append(panel)
    return panels


def by_idname(panels=None):
    return {
        getattr(panel, "bl_idname", panel.__name__): panel
        for panel in (panels if panels is not None else panel_types())
    }


def depth(panel, lookup):
    result = 0
    seen = set()
    parent_id = getattr(panel, "bl_parent_id", "")
    while parent_id and parent_id not in seen and parent_id in lookup:
        seen.add(parent_id)
        result += 1
        parent_id = getattr(lookup[parent_id], "bl_parent_id", "")
    return result


def reregister(panels, mutate, label="Power Panel"):
    panels = list(dict.fromkeys(panels))
    lookup = by_idname(panels)
    removed = []
    for panel in sorted(panels, key=lambda item: depth(item, lookup), reverse=True):
        try:
            bpy.utils.unregister_class(panel)
            removed.append(panel)
        except (RuntimeError, ValueError) as exc:
            print(f"[{label}] Could not unregister {panel.__name__}: {exc}")

    mutate(removed)
    pending = set(removed)
    for panel in sorted(removed, key=lambda item: depth(item, lookup)):
        try:
            bpy.utils.register_class(panel)
            pending.discard(panel)
        except (RuntimeError, ValueError):
            pass
    for panel in list(pending):
        try:
            bpy.utils.register_class(panel)
            pending.discard(panel)
        except (RuntimeError, ValueError) as exc:
            print(f"[{label}] Restore failed for {panel.__name__}: {exc}")
    return not pending


def sidebar_region(area):
    if area is None or area.type != "VIEW_3D":
        return None
    return next((region for region in area.regions if region.type == "UI"), None)


def registered_categories():
    return {
        getattr(panel, "bl_category", "")
        for panel in panel_types()
        if getattr(panel, "bl_category", "")
    }

