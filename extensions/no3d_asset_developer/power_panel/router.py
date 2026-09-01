"""Reversible intent-based routing for configured 3D View sidebar panels."""

from dataclasses import dataclass

from . import config, discovery


@dataclass(frozen=True)
class Snapshot:
    category: str
    order: int
    parent: str


_snapshots = {}


def _panel_id(panel):
    return getattr(panel, "bl_idname", panel.__name__)


def restore_routes():
    panels = [panel for panel in _snapshots if getattr(panel, "is_registered", False)]
    if not panels:
        _snapshots.clear()
        return True

    def mutate(removed):
        for panel in removed:
            snapshot = _snapshots[panel]
            panel.bl_category = snapshot.category
            panel.bl_order = snapshot.order
            panel.bl_parent_id = snapshot.parent

    result = discovery.reregister(panels, mutate, "Power Panel Router")
    _snapshots.clear()
    return result


def apply_routes():
    panels = discovery.panel_types()
    lookup = discovery.by_idname(panels)
    desired = {}

    for panel_id, route in config.PANEL_ROUTES.items():
        panel = lookup.get(panel_id)
        if panel is None:
            continue
        current = Snapshot(
            getattr(panel, "bl_category", ""),
            getattr(panel, "bl_order", 0) or 0,
            getattr(panel, "bl_parent_id", ""),
        )
        target_parent = "" if route.detach_parent else current.parent
        target = Snapshot(route.category, route.order, target_parent)
        if current == target:
            continue
        _snapshots.setdefault(panel, current)
        desired[panel] = target

    # Normalize only the Agent Bridge class from retired/mutated categories.
    agent = lookup.get("AGENT_BRIDGE_PT_panel")
    if agent is not None and getattr(agent, "bl_category", "") != "Agent":
        current = Snapshot(
            getattr(agent, "bl_category", ""),
            getattr(agent, "bl_order", 0) or 0,
            getattr(agent, "bl_parent_id", ""),
        )
        # Never restore the retired Claude category or the stale merged Dev
        # category after Power Panel is disabled.
        _snapshots[agent] = Snapshot("Agent", current.order, current.parent)
        desired[agent] = Snapshot("Agent", 10, current.parent)

    if not desired:
        return True

    def mutate(removed):
        for panel in removed:
            target = desired[panel]
            panel.bl_category = target.category
            panel.bl_order = target.order
            panel.bl_parent_id = target.parent

    result = discovery.reregister(desired, mutate, "Power Panel Router")
    print(f"POWER_PANEL_ROUTER_OK routed={len(desired)}")
    return result
