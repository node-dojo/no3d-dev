"""Host AddonPreferences integration for Power Panel slot assignments."""

from bpy.props import EnumProperty

from . import config, discovery, slots


_enum_cache = {}
_item_callbacks = {}


def _category_items_for_slot(slot):
    categories = set(config.DESTINATION_ORDER)
    categories.update(
        slots.canonical_category(category)
        for category in discovery.registered_categories()
    )
    default = config.DEFAULT_SLOTS[slot]
    items = []
    if default:
        items.append((default, default, f"Default destination for slot {slot}"))
    items.append(("NONE", "Unassigned", "Reserve this slot"))
    items.extend(
        (category, category, f"Open the {category} sidebar category")
        for category in sorted(categories, key=str.casefold)
        if category and category != default
    )
    _enum_cache[slot] = items
    return items


def _callback_for_slot(slot):
    def items(_self, _context):
        return _category_items_for_slot(slot)
    _item_callbacks[slot] = items
    return items


def _assignment_updated(_self, _context):
    from . import schedule_reconcile
    schedule_reconcile(0.05)


def install_properties(preferences_class):
    annotations = preferences_class.__annotations__
    for slot in range(1, 10):
        name = f"{config.SLOT_PROPERTY_PREFIX}{slot}"
        if name in annotations:
            continue
        annotations[name] = EnumProperty(
            name=f"Slot {slot}",
            description=f"Power Panel destination assigned to number {slot}",
            items=_callback_for_slot(slot),
            update=_assignment_updated,
        )


def draw(layout, preferences):
    box = layout.box()
    box.label(text="Power Panel", icon="MENU_PANEL")
    box.label(text="Option+Tab, then click, gesture, or press a slot number", icon="INFO")
    grid = box.grid_flow(columns=2, even_columns=True, align=True)
    for slot in range(1, 10):
        grid.prop(preferences, f"{config.SLOT_PROPERTY_PREFIX}{slot}", text=f"{slot}")
