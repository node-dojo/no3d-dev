# NO3D Power Panel Radial Config

[← Local Panel Router Config](local-panel-router-config.md) ·
[N-Panel Chaos Control](../N-Panel%20Chaos%20Control.md) ·
[Numbered Tab Slots Config →](numbered-tab-slots-config.md)

Status: **Native Blender Power Panel pie implemented**<br>
Revision: **5**<br>
Shortcut: **Option+Tab default; editable in No3d Dev preferences**

This document is both a spatial sketch and the canonical action assignment for
the native Power Panel pie. Edit the spatial map first, then keep the
direction table synchronized so implementation never has to infer intent from
geometry alone.

The interface uses Blender's stock pie menu. Native item order is also native
number-key order: West, East, South, North, Northwest, Northeast, Southwest,
Southeast correspond to 1–8. The configured destinations are arranged to keep
their stable slot IDs aligned with those accelerators.

## Spatial editor

The center is the gesture origin and cancel zone; it is not an action slot.

| ↖ Northwest | ↑ North | ↗ Northeast |
|:---:|:---:|:---:|
| **5 Agent Bridge**<br>`TAB:Agent` | **4 No3D Tools**<br>`TAB:No3D Tools` | **6 Search All Tabs**<br>`OP:Search Sidebar Tabs` |
| **← 1 NO3D Dev**<br><br>`TAB:NO3D Dev` | **CENTER**<br><br>gesture origin<br>release to cancel | **2 NO3D Create →**<br><br>`TAB:NO3D Create` |
| **↙ 7 Toggle Sidebar**<br>`OP:Toggle Sidebar` | **↓ 3 NO3D Capture**<br>`TAB:NO3D Capture` | **8 Last Used Tab ↘**<br>`OP:Previous Sidebar Tab` |

## Canonical direction table

Blender's native pie API consumes entries in the direction and number order
shown below; implementation and documentation must retain this order.

| Enabled | Direction | Stable slot ID | Label | Action kind | Target/operator | Fallback if unavailable |
| --- | --- | --- | --- | --- | --- | --- |
| Yes | West | `dev` | NO3D Dev | Tab | `NO3D Dev` | Open Search All Tabs |
| Yes | East | `create` | NO3D Create | Tab | `NO3D Create` | Open Search All Tabs |
| Yes | South | `capture` | NO3D Capture | Tab | `NO3D Capture` | Open Search All Tabs |
| Yes | North | `tools` | No3D Tools | Tab | `No3D Tools` | Open Search All Tabs |
| Yes | Northwest | `agent` | Agent Bridge | Tab | `Agent` | Open Search All Tabs |
| Yes | Northeast | `search` | Search All Tabs | Operator | `view3d.no3d_search_sidebar_tabs` | Report unavailable |
| Yes | Southwest | `toggle` | Toggle Sidebar | Operator | `view3d.toggle_region` configured for UI | Report unavailable |
| Yes | Southeast | `previous` | Last Used Tab | Operator | `view3d.no3d_previous_sidebar_tab` | Open Search All Tabs |

## Behavior configuration

| Setting | Draft value | Implementation meaning |
| --- | --- | --- |
| Open sidebar when choosing a tab | `Yes` | Set `space.show_region_ui = True` before activation. |
| Remember previous category per 3D View | `Yes` | Store by area identity where practical; fall back to last global category. |
| Hide unavailable tab slots | `No` | Preserve spatial muscle memory; disabled targets invoke Search All Tabs. |
| Show icons | `No` | Current overlay prioritizes stable geometry, full names, and slot numbers. |
| Show shortcut hints | `No` | Keep the pie visually quiet. |
| Show numbered slot prefixes | `Yes` | Read stable numbers from Numbered Tab Slots Config; do not maintain a second assignment list here. |
| Wrap native tabs into pie | `No` | Search All Tabs remains the route to native and unrelated categories. |
| Pie shortcut | `Option+Tab` | Registered through Blender's editable add-on keymap; no active live-profile collision at approval time. |
| Number selection | Native `1`–`8` while open | Selects native pie items in order without global number bindings. |

## Interaction contract

1. Invoke from any region of an active 3D View.
2. Keep every enabled direction spatially stable across revisions.
3. Selecting a tab opens the sidebar and activates the exact configured
   category.
4. Missing categories do not collapse or rotate the pie; use the configured
   fallback.
5. Search All Tabs invokes the popup fallback; F5 independently enters the
   persistent live-filter field.
6. Escape or release in the center cancels without changing the active tab.
7. The pie must not save user preferences or hard-code over an occupied user
   shortcut.

## Revision workflow

For each new version:

1. Increment `Revision` above.
2. Edit the spatial map.
3. Mirror every change into the canonical direction table.
4. Record the change below.
5. Implement from the direction table.
6. Verify the live geometry and every fallback in Blender.

## Revision notes

- **Revision 5:** Promoted Blender's native pie to the Option+Tab interface,
  removed the custom GPU/modal renderer, and aligned the first five compass
  positions with native 1–5 selection. Utilities occupy native slots 6–8.
- **Revision 3:** Implemented the named compass directions as a custom radial
  overlay, with search/toggle/previous utilities and invoked number-row
  selection. Slot assignments now come from editable No3d Dev preferences. No
  global modifier-number bindings are installed; the native pie is fallback
  only because it consumes number events.
- **Revision 4:** Replaced the northwest Eyecones destination with Agent
  Bridge, targeting the standalone `Agent` sidebar category.
- **Revision 2:** Implemented the numbered N-panel pie with an editable
  `Option+Tab` default. It reads the Numbered Tab Slots mapping rather than
  duplicating assignments. The dropdown assignment editor remains pending.
- **Revision 1:** Initial five-destination layout with search, sidebar toggle,
  and previous-tab utilities. Shortcut intentionally deferred until live
  keymap conflicts are inspected.
