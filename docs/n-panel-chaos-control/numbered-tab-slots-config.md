# Numbered Tab Slots Config

[← Navigation Pie Config](navigation-pie-config.md) ·
[Local Panel Router Config](local-panel-router-config.md) ·
[N-Panel Chaos Control](../N-Panel%20Chaos%20Control.md)

Status: **Implemented through Power Panel**  
Revision: **5**  
Access gesture: **Option+Tab, then click/gesture or number**

This document assigns stable numeric identities to high-frequency N-panel
destinations. It follows the same idea as numbered output-node slots: the
number remains attached to the intended destination, provides a visible cue,
and becomes a direct selection key while the Power Panel pie is invoked.

## Editing rules

- Assign each enabled slot to one canonical, unprefixed category name from the
  Local Panel Router Config.
- Slot numbers never compact automatically. If slot 2 is unavailable, slot 3
  remains slot 3.
- Change `Display prefix` to alter presentation without changing the slot's
  identity or shortcut.
- Set `Enabled` to `No` to reserve a number without exposing or binding it.
- Do not install global modifier+number bindings. Number keys are interpreted
  only during an invoked Power Panel interaction.
- Numbering is local-profile behavior. Public add-ons keep their shipped tab
  names outside the No3d Dev routing environment.

## Slot assignments

| Enabled | Slot | Stable slot ID | Canonical category | Display prefix | Displayed tab label | Missing-category behavior | Notes |
| --- | ---: | --- | --- | --- | --- | --- | --- |
| Yes | 1 | `dev` | `NO3D Dev` | `[1]` | `[1] NO3D Dev` | Open Search Tabs filtered to `NO3D` | Highest-frequency development controls. |
| Yes | 2 | `create` | `NO3D Create` | `[2]` | `[2] NO3D Create` | Open Search Tabs filtered to `NO3D` | Viewport creation and framing. |
| Yes | 3 | `capture` | `NO3D Capture` | `[3]` | `[3] NO3D Capture` | Open Search Tabs filtered to `NO3D` | Screenshots, renders, and media. |
| Yes | 4 | `tools` | `No3D Tools` | `[4]` | `[4] No3D Tools` | Open Search Tabs filtered to `No3D Tools` | Public product workflows. |
| Yes | 5 | `agent` | `Agent` | `[5]` | `[5] Agent` | Open Search Tabs filtered to `Agent Bridge` | Standalone Agent Bridge access. |
| No | 6 | `slot_6` | — | `[6]` | — | Report unassigned | Reserved. |
| No | 7 | `slot_7` | — | `[7]` | — | Report unassigned | Reserved. |
| No | 8 | `slot_8` | — | `[8]` | — | Report unassigned | Reserved. |
| No | 9 | `slot_9` | — | `[9]` | — | Report unassigned | Reserved. |

## Shortcut configuration

| Setting | Draft value | Implementation meaning |
| --- | --- | --- |
| Invocation | `Option+Tab` | Opens the Power Panel spatial pie. |
| Number row | `1`–`9` | Use the main number row, not the numeric keypad. |
| Open closed sidebar | `Yes` | Set `space.show_region_ui = True` before activation. |
| Activate unavailable slot | `Fallback` | Keep the number stable and execute its configured fallback. |
| Editable assignments | `Yes` | Render slot destination dropdowns in No3d Dev preferences. |
| Save user preferences automatically | `No` | Registration is runtime-owned; the add-on never saves preferences. |

No global number bindings are generated. The earlier collision audit remains
useful evidence for why the invoked mode is preferable, but its `Ctrl+Alt`
candidate is superseded.

Candidate modifiers must be audited rather than assumed:

| Candidate | Status | Known concern |
| --- | --- | --- |
| Shift + number | Rejected for now | Shift+1 creates GeoNode Object and Shift+5 imports Image as Mesh Plane. |
| Ctrl + number | Rejected | `1`–`5` collide with subdivision levels; `1`–`3` also collide with mesh/UV selection and cleanup. |
| Alt + number | Rejected | `1`–`9` collide with collection visibility in Object and Pose modes. |
| Command + number | Rejected | `1`–`5` collide with subdivision levels; `1`–`3` also collide with mesh/UV selection. |
| Ctrl + Shift + number | Rejected | `1`–`3` collide with mesh/UV selection; `4` collides with STL Export. |
| Shift + Alt + number | Rejected | `1`–`9` collide with collection visibility. |
| Ctrl + Alt + number | Superseded | Was conflict-free, but reserving nine global shortcuts is unnecessary. |
| Command + Alt + number | Viable alternative | No active `1`–`9` conflicts, but more likely to overlap macOS/application conventions. |
| Ctrl + Command + number | Viable alternative | No active `1`–`9` conflicts, but less comfortable and semantically less clear. |

### Live collision audit — 2026-08-31

Audited the active Blender 5.2 profile in `Soon Cages Manu Constraints.001`
across user, add-on, and default keyconfigs, including all 3D View modes and
the Window keymap. This is a runtime snapshot and should be rerun if the
profile or major add-on set changes.

- Plain and Shift numbers are established creation/selection workflows.
- Ctrl and Command numbers own subdivision and selection behavior through 5.
- Alt and Shift+Alt numbers own collection visibility through 9.
- `Ctrl+Alt`, `Command+Alt`, and `Ctrl+Command` were empty for all nine slots.
- The final design uses one Option+Tab entry gesture and handles number keys
  only while Power Panel is active.

## Display and search contract

1. Prefix only configured destination categories after local routing resolves
   their canonical names.
2. Preserve the canonical name separately from the displayed label.
3. Match search input against the prefix, slot number, canonical name, visible
   name, and configured aliases.
4. Searching `1`, `[1]`, `dev`, or `no3d dev` should all find slot 1.
5. Use the same displayed prefix in the navigation pie when that feature is
   enabled.
6. Numeric prefixing participates in the programmatic category order after
   Blender-native tabs.
7. Clearing or disabling numbering restores the canonical category names.

## Implementation contract

1. Load this slot mapping after the Local Panel Router has established its
   canonical destinations.
2. Snapshot original category names before adding prefixes.
3. Re-register only affected panels, children before parents on removal and
   parents before children on restoration.
4. Implement one operator such as `view3d.no3d_open_sidebar_slot` with an
   integer `slot` property instead of nine separate operators.
5. Route number-row input from the invoked Power Panel controller; do not
   generate nine global keymap items.
6. Keep a slot-to-canonical-category lookup independent of visible prefixes.
7. Restore every original category and generated keymap when numbering is
   disabled or the extension unregisters.
8. Read back live categories and keymaps after every revision.

## Acceptance criteria

- Each enabled destination displays its configured `[n]` prefix.
- Invoked numeric access opens the correct category and sidebar.
- Missing categories do not renumber later slots.
- Search and pie navigation resolve both canonical and numbered names.
- Disabling the feature restores exact unprefixed names and removes generated
  shortcuts.
- No existing number shortcut is replaced.

## Revision workflow

1. Increment `Revision` above.
2. Edit the Slot Assignments table.
3. Audit shortcut conflicts if the modifier changes.
4. Record the decision and conflicts below.
5. Implement directly from the table.
6. Verify visible prefixes, direct access, fallbacks, and restoration live.

## Revision notes

- **Revision 5:** Replaced slot 5 Eyecones with the standalone `Agent`
  category, labeled Agent Bridge in the Power Panel radial interface.
- **Revision 4:** Superseded global `Ctrl+Alt+number` with Option+Tab followed
  by click/gesture or an invoked number-row selection. Added editable slot
  dropdowns through the Power Panel feature suite.
- **Revision 3:** Restored Agent as its own unnumbered tab and completed the
  live 3D View modifier+number collision audit. `Ctrl+Alt+1`–`9` is the
  recommended open family, pending approval. F5 is independently assigned to
  Search Sidebar Tabs and does not determine the numbered-slot modifier.
- **Revision 2:** Implemented visible prefixes for categories that currently
  exist. Slots 2 and 3 remain absent and reserved until Local Panel Router
  creates their canonical destinations. Direct number shortcuts remain
  deferred pending modifier approval.
- **Revision 1:** Added provisional slots 1–5 for the five proposed routed
  destinations. Modifier intentionally unassigned; Shift is excluded by
  established Shift+1 and Shift+5 workflows.
