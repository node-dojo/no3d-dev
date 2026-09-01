# NO3D Power Panel Radial Config

[← Local Panel Router Config](local-panel-router-config.md) ·
[N-Panel Chaos Control](../N-Panel%20Chaos%20Control.md) ·
[Numbered Tab Slots Config →](numbered-tab-slots-config.md)

Status: **Power Panel spatial pie implemented**  
Revision: **4**  
Shortcut: **Option+Tab default; editable in No3d Dev preferences**

This document is both a spatial sketch and the canonical action assignment for
the Power Panel radial overlay. Edit the spatial map first, then keep the
direction table synchronized so implementation never has to infer intent from
geometry alone.

The overlay intentionally uses a small custom modal interaction instead of
Blender's stock pie menu. Stock pies own subsequent number-key events; Power
Panel needs those same unmodified keys to select editable slots while the
overlay is open. A native menu class remains available only as a fallback.

## Spatial editor

The center is the gesture origin and cancel zone; it is not an action slot.

| ↖ Northwest | ↑ North | ↗ Northeast |
|:---:|:---:|:---:|
| **Agent Bridge**<br>`TAB:Agent` | **NO3D Create**<br>`TAB:NO3D Create` | **Search All Tabs**<br>`OP:Search Sidebar Tabs` |
| **← West**<br><br>**NO3D Dev**<br>`TAB:NO3D Dev` | **CENTER**<br><br>gesture origin<br>release to cancel | **East →**<br><br>**No3D Tools**<br>`TAB:No3D Tools` |
| **↙ Toggle Sidebar**<br>`OP:Toggle Sidebar` | **↓ NO3D Capture**<br>`TAB:NO3D Capture` | **Last Used Tab ↘**<br>`OP:Previous Sidebar Tab` |

## Canonical direction table

The fallback Blender pie API consumes slots in its own call order;
implementation must map these named directions explicitly rather than relying
on table or source order.

| Enabled | Direction | Stable slot ID | Label | Action kind | Target/operator | Fallback if unavailable |
| --- | --- | --- | --- | --- | --- | --- |
| Yes | West | `dev` | NO3D Dev | Tab | `NO3D Dev` | Open Search All Tabs |
| Yes | East | `tools` | No3D Tools | Tab | `No3D Tools` | Open Search All Tabs |
| Yes | South | `capture` | NO3D Capture | Tab | `NO3D Capture` | Open Search All Tabs |
| Yes | North | `create` | NO3D Create | Tab | `NO3D Create` | Open Search All Tabs |
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
| Number selection | `1`–`9` while invoked | Opens the corresponding editable slot without global number bindings. |

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
