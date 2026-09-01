"""Supported active-category activation for Blender's dynamic sidebar enum."""

import bpy

from . import discovery


def activate_area(area, category):
    """Prime Blender's dynamic enum and activate *category* in this 3D View.

    `Region.active_panel_category` can appear read-only until its runtime enum
    items have been resolved. Asking UILayout for the item's display name
    materializes that dynamic item before assignment.
    """
    region = discovery.sidebar_region(area)
    if region is None:
        return False
    try:
        item_name = bpy.types.UILayout.enum_item_name(
            region, "active_panel_category", category
        )
        if not item_name:
            return False
        region.active_panel_category = category
        region.tag_redraw()
        return True
    except (AttributeError, TypeError, ValueError):
        return False


def activate(context, category):
    return activate_area(context.area, category)


def unregister():
    pass
