"""Own the 3D View sidebar tab order without a CleanPanels dependency.

Blender has no declarative tab-order property.  Sidebar categories are created
in panel registration order, so the supported practical mechanism is the one
CleanPanels also uses: unregister the affected panels and register them again
in the desired category order.  Parent/child relationships are preserved.
"""

from __future__ import annotations

import bpy

from . import config, discovery


NATIVE_CATEGORY_ORDER = ("Item", "Tool", "View")
NO3D_CATEGORY_ORDER = (
    "[1] NO3D Dev",
    "NO3D Dev",
    "[5] Agent",
    "Agent",
    "[2] NO3D Create",
    "NO3D Create",
    "[3] NO3D Capture",
    "NO3D Capture",
    "[4] No3D Tools",
    "No3D Tools",
    "Eyecones",
    "No3d Cam",
    "Send Nodes",
)
NO3D_MODULES = {
    "agent_bridge",
    "no3d_asset_developer",
    "no3d_cad_wip",
    "no3d_camera_utilities",
    "no3d_data_pipe",
    "no3d_save_reload",
    "send_nodes",
}

_reordering = False


def _module_owner(panel_type: type) -> str:
    module = getattr(panel_type, "__module__", "")
    if module.startswith("bl_ext."):
        parts = module.split(".")
        # Extension modules are ``bl_ext.<repository>.<extension_id>...``.
        # The repository segment (often ``user_default``) is not the owner.
        return parts[3] if len(parts) > 3 else module
    return module.split(".", 1)[0]


def _view3d_sidebar_panels() -> list[type]:
    # ``dir(bpy.types)`` is incomplete for some dynamically registered
    # extension classes. Walk Blender's actual Python subclass registry so a
    # live reorder cannot silently omit panels and split a category.
    return [
        panel
        for panel in discovery.panel_types()
        if getattr(panel, "bl_category", "")
    ]


def _category_key(category: str, panels: list[type]) -> tuple[int, int | str, str]:
    if category in NATIVE_CATEGORY_ORDER:
        return (0, NATIVE_CATEGORY_ORDER.index(category), category.casefold())
    # Any category actually supplied by Blender's bundled ``bl_ui`` package is
    # native too (for example Animation in some startup configurations).
    if any(_module_owner(panel) == "bl_ui" for panel in panels):
        return (1, category.casefold(), category.casefold())
    if category in NO3D_CATEGORY_ORDER:
        return (2, NO3D_CATEGORY_ORDER.index(category), category.casefold())
    if any(_module_owner(panel) in NO3D_MODULES for panel in panels):
        return (3, category.casefold(), category.casefold())
    return (4, category.casefold(), category.casefold())


def _panel_depth(panel_type: type, by_idname: dict[str, type]) -> int:
    return discovery.depth(panel_type, by_idname)


def apply_npanel_order() -> bool:
    """Put native tabs first, then NO3D tabs, then every other add-on tab."""
    global _reordering
    if _reordering:
        return False

    panels = _view3d_sidebar_panels()
    if not panels:
        return False

    _reordering = True
    try:
        by_idname = {
            getattr(panel, "bl_idname", panel.__name__): panel for panel in panels
        }
        grouped: dict[str, list[type]] = {}
        for panel in panels:
            grouped.setdefault(panel.bl_category, []).append(panel)

        categories = sorted(
            grouped,
            key=lambda category: _category_key(category, grouped[category]),
        )
        top_level = []
        children = []
        for category in categories:
            category_panels = sorted(
                grouped[category],
                key=lambda panel: (
                    getattr(panel, "bl_order", 0) or 0,
                    getattr(panel, "bl_label", "").casefold(),
                    panel.__name__,
                ),
            )
            top_level.extend(
                panel for panel in category_panels if _panel_depth(panel, by_idname) == 0
            )
            children.extend(
                panel for panel in category_panels if _panel_depth(panel, by_idname) > 0
            )

        # Register every category-bearing root first. Children do not create
        # tabs, so registering them afterward preserves category order while
        # satisfying cross-category parent relationships used by some add-ons.
        ordered = top_level + sorted(
            children,
            key=lambda panel: (
                _panel_depth(panel, by_idname),
                getattr(panel, "bl_order", 0) or 0,
                panel.__name__,
            ),
        )

        removed = []
        for panel in sorted(
            panels,
            key=lambda item: (_panel_depth(item, by_idname), item.__name__),
            reverse=True,
        ):
            try:
                bpy.utils.unregister_class(panel)
                removed.append(panel)
            except (RuntimeError, ValueError) as exc:
                print(f"[NO3D N-Panel] Could not unregister {panel.__name__}: {exc}")

        removed_set = set(removed)
        for panel in ordered:
            if panel not in removed_set:
                continue
            try:
                bpy.utils.register_class(panel)
                removed_set.remove(panel)
            except (RuntimeError, ValueError) as exc:
                print(f"[NO3D N-Panel] Could not register {panel.__name__}: {exc}")

        # Never knowingly leave a foreign panel unregistered after a partial
        # failure. A second pass handles parents that became available late.
        for panel in sorted(
            removed_set,
            key=lambda item: (_panel_depth(item, by_idname), item.__name__),
        ):
            try:
                bpy.utils.register_class(panel)
            except (RuntimeError, ValueError) as exc:
                print(f"[NO3D N-Panel] Restore failed for {panel.__name__}: {exc}")

        print("NO3D_NPANEL_ORDER_OK")
        return True
    finally:
        _reordering = False


def register():
    pass


def unregister():
    pass
