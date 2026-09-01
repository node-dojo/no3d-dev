# N-Panel Chaos Control

Implementation name: **Power Panel**. Power Panel is an internal feature suite
of No3d Asset Developer, not another visible sidebar tab. Its package owns the
router, ordering, live filter, popup fallback, numbered bookmarks, spatial pie,
keymaps, and assignment controls through one lifecycle boundary.

## Working configuration documents

- [Local Panel Router Config](n-panel-chaos-control/local-panel-router-config.md)
  — editable panel-to-category assignments, ordering, and runtime behavior.
- [NO3D Navigation Pie Config](n-panel-chaos-control/navigation-pie-config.md)
  — spatial pie layout plus canonical direction/action assignments.
- [Numbered Tab Slots Config](n-panel-chaos-control/numbered-tab-slots-config.md)
  — stable `[1]`, `[2]`, `[3]` tab identities and direct-access shortcuts.

These documents are the reusable configuration surface for future revisions.
Edit them first when changing the proposed organization; implementation should
then follow the latest explicit revision rather than re-deriving the structure
from prose or the current Blender UI.

## Problem

The 3D View sidebar has become an expensive navigation surface. The current
development profile has 28 distinct category names backed by 194 registered
panel classes. Finding a tab repeatedly requires narrow-target hover scrolling,
and compact tabs reduce unfamiliar names to ambiguous initials or monochrome
icons.

The pressure comes from several sources:

- Add-ons create one tab per package instead of grouping by creative intent.
- Some add-ons fragment themselves across multiple category names.
- Category strings are exact and case-sensitive, so `NO3D Dev` and
  `No3D Dev` become separate tabs.
- Long-running Blender processes retain already-registered panel classes after
  source category names change.
- Blender exposes one shared sidebar-tab theme color, not per-category fills.
- Compact-mode PNG and built-in icons are useful silhouettes, but Blender
  renders them uniformly through the current monochrome theme.

## Current high-value cleanup targets

- Merge `NO3D Dev` and `No3D Dev`.
- Retire the stale `Claude` category in favor of a dedicated `Agent` tab.
- Reconcile `Hardflow`, `HardOps`, and `Hops` where their add-on permits it.
- Reconcile `BlendAR` and `Dojo AR`.
- Reconcile BlenderKit and N++ panels split across `Blendkit`, `N++`, and
  `extra`.
- Keep Blender-native `Item`, `Tool`, `View`, and `Animation` ahead of NO3D
  tabs, followed by unrelated installed add-ons.

## Proposed intent-based NO3D structure

| Category | Purpose | Proposed contents |
| --- | --- | --- |
| `NO3D Dev` | Develop, inspect, and ship tools | Asset Manager, Dev Notes, Stowaway Inspector, WIP tools, CAD.wip |
| `Agent` | Connect live Blender sessions to coding agents | Agent Bridge serving, instances, handoff, instructions, terminal launch |
| `NO3D Create` | Everyday viewport creation | Paste Clipboard, View Align, Toolbox, Aspect Overlay, Camera Framing, Selected Mesh Fit |
| `NO3D Capture` | Produce images and media | Viewport Screenshot, Editor Screenshot, Transparent Media, Camera Render |
| `No3D Tools` | Public product workflows | Print Pipeline, printer/output/multipart settings, Send |
| `Eyecones` | Eyecones-specific operation | Transport, OSC, Spotify, displays, timelapse, and related controls |

This routing should be local-profile behavior. Public extensions can retain
their customer-facing default categories while No3d Dev regroups their panels
inside the development environment.

Send Nodes remains in the Node Editor sidebar. Power Panel governs the 3D View
sidebar and does not relocate panels between editor types.

## Planned fixes

### 1. Live in-place tab filter — implementing first

- Replace the header's large popup button with an inline text field.
- After a short debounce, temporarily unregister panels belonging to
  nonmatching categories so the actual N-panel tab strip contains only matches.
- Match visible category names, configured aliases, and the visible labels of
  every panel in that category. Never match internal class IDs.
- Treat each category as one result: a match from any label or alias keeps the
  complete tab and all its panels.
- Enable Blender's `TEXTEDIT_UPDATE` behavior so filtering reacts to every
  typed character without Enter.
- Apply conservative fuzzy token matching for misspellings such as `agnet` and
  `camra`; one- and two-character input remains strict to avoid noisy results.
- Keep the field, clear button, and popup fallback visible while filtering.
- Restore every hidden panel on clear, add-on shutdown, or partial failure.
- Preserve required parent panels when third-party add-ons use cross-category
  parent relationships; correctness takes priority over hiding one dependency
  tab during this experimental tranche.
- Do not save the query or mutate Blender user preferences.

### 2. Searchable tab switcher — retained as fallback

- Add a Blender search popup listing the currently usable 3D View sidebar
  categories.
- Use incremental type-to-filter behavior: typing `no3d`, `cam`, `agent`, and
  so on narrows the list.
- Selecting a result opens the sidebar and activates that category directly.
- First expose `Search Tabs…` visibly in the 3D View Tool Settings header and
  verify the popup and category switching interactively.
- The header workflow has passed; plain F5 enters keyboard-driven live filter
  mode beside the existing F3 Search and F4 Import Options workflow. Typed
  characters update the persistent header field and actual tabs directly;
  Enter keeps the filter, Esc clears it, and F5 exits input mode.
- Preserve Shift+5 for Import Image as Mesh Plane.
- Disable exact plain-F5 conflicts such as `rsv.quicksave` while No3d Dev is
  enabled, and restore them when it is disabled. Leave modified F5 gestures
  untouched.
- Expose the operator through F3 as `Search Sidebar Tabs`.

### 3. Local panel router — implemented in Power Panel

- Add an opt-in No3d Dev routing table that regroups installed NO3D panels by
  creative intent without changing their public source defaults.
- Normalize exact category names before ordering.
- Discover dynamic panels through Blender's Panel subclass registry rather
  than relying on incomplete `dir(bpy.types)` enumeration.
- Reapply routing after file load and add-on registration changes.
- Use the linked Local Panel Router Config as the implementation source.

### 4. Power Panel navigation pie — implemented

- Invoke the compact spatial pie with Option+Tab.
- Use fixed spatial positions for `NO3D Dev`, `NO3D Create`, `NO3D Capture`,
  `No3D Tools`, and `Agent` (shown as Agent Bridge in Power Panel).
- Include Search All Tabs and Toggle Sidebar utility entries.
- Select by gesture/click or number row while invoked. Do not install global
  modifier-number shortcuts.
- Use the linked NO3D Navigation Pie Config as the implementation source.

### 5. Numbered tab slots — implemented

- Assign important local tabs stable numeric identities displayed as
  `[1] NO3D Dev`, `[2] NO3D Create`, and so on.
- Open a slot from the invoked Power Panel with its number key.
- Keep slot assignments stable when an add-on or category is unavailable;
  never shift later tabs down to fill a gap.
- Generate keymaps from the linked Numbered Tab Slots Config rather than
  hard-coding individual shortcuts.
- Make numbered names searchable both with and without their prefix.
- Use the same numbers in pie labels and other navigation surfaces.
- Apply prefixes only to destinations that currently exist. Slots 2 and 3 stay
  reserved until the Local Panel Router creates `NO3D Create` and
  `NO3D Capture`; later slots never compact upward.
- Expose editable slot destination dropdowns in No3d Dev preferences while
  retaining useful defaults and stable slot IDs.

### 6. Secondary visual cues

- Remove the colored-emoji experiment; compact rendering collapses it into the
  same monochrome icon treatment.
- Consider distinct built-in or PNG silhouettes only as secondary cues after
  consolidation and navigation are working.
- Do not build a GPU overlay over Blender's tab strip: Python cannot reliably
  access its bounds, scrolling, or hit regions, making that approach fragile.

## Acceptance criteria

- A user can reach any currently usable sidebar category by invoking one
  command, typing part of its name, and confirming.
- Configured numbered tabs retain the same number across sessions and can be
  opened directly once a non-conflicting modifier is approved.
- The switcher works in the active 3D View and opens a closed sidebar.
- The Tool Settings header exposes a working `Search Tabs…` control.
- Typing in the Tool Settings filter leaves only matching actual N-panel tabs;
  clearing it restores the complete registered panel set.
- Available configured destinations show stable numeric prefixes without
  compacting around unavailable slots.
- F5 enters live tab-filter input mode; Shift+5 remains Import Image as Mesh
  Plane. The category-list popup remains available only from the header
  dropdown and through Blender operator search.
- Native categories remain ahead of NO3D categories.
- Only one exact `NO3D Dev` category exists after routing.
- No stale `Claude` category remains.
- Registration/unregistration passes under Blender 5.2 factory startup.
- Live verification reads back actual registered categories and keymaps; source
  inspection alone is not acceptance.
