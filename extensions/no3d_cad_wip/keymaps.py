"""Declarative default shortcuts for No3d CAD.wip."""

from __future__ import annotations

from dataclasses import dataclass

from . import ids


@dataclass(frozen=True)
class ShortcutSpec:
    keymap: str
    space_type: str
    operator: str
    key: str
    shift: bool = False
    oskey: bool = False
    ctrl: bool = False
    alt: bool = False


SHORTCUTS = (
    ShortcutSpec("Node Editor", "NODE_EDITOR", ids.FEATURE_TOOL_SEARCH_OT, "F", shift=True),
    ShortcutSpec("3D View", "VIEW_3D", ids.ADD_MESH_LINE_OT, "FOUR", shift=True),
    ShortcutSpec(
        "3D View", "VIEW_3D", ids.ADD_MESH_LINE_FEATURE_OT, "FOUR", shift=True, oskey=True,
    ),
    ShortcutSpec(
        "3D View", "VIEW_3D", ids.EMBED_SELECTED_FTOOLS_OT, "F", shift=True, oskey=True,
    ),
)
