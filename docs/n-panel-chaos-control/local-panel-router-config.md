# Local Panel Router Config

[← N-Panel Chaos Control](../N-Panel%20Chaos%20Control.md) ·
[Navigation Pie Config](navigation-pie-config.md) ·
[Numbered Tab Slots Config →](numbered-tab-slots-config.md)

Status: **Implemented through Power Panel**  
Revision: **3**  
Scope: **Joe's local Blender development profile only**

This is the editable source for local N-panel routing. Public add-ons retain
their shipped category names; No3d Dev temporarily re-registers matching live
panels into the destinations below and restores their original categories when
the router is disabled or unregistered.

## Editing rules

- Change a row's `Destination` to move it.
- Set `Enabled` to `No` to leave a panel under its add-on's original category.
- Use registered panel class IDs as stable selectors; labels are explanatory.
- A parent and its children should normally share a destination. When only a
  parent is listed, its registered descendants follow it unless explicitly
  overridden by another row.
- `Order` is relative within the destination category; lower values appear
  first. Leave gaps for later insertions.
- Unknown or unavailable class IDs are skipped and reported, never treated as
  a reason to unregister unrelated panels.

## Destination order

1. `NO3D Dev`
2. `Agent`
3. `NO3D Create`
4. `NO3D Capture`
5. `No3D Tools`
6. `Eyecones`

Blender-native tabs remain ahead of this list. Other installed add-ons follow
the NO3D destinations.

Visible numeric prefixes are owned by the linked Numbered Tab Slots Config,
not duplicated in this routing table. This document uses canonical unprefixed
destination names so routing remains stable when numbering is disabled.

## Routes

### NO3D Dev — develop, inspect, and ship

| Enabled | Panel class ID | Current label | Source | Destination | Order | Notes |
| --- | --- | --- | --- | --- | ---: | --- |
| Yes | `NO3D_PT_extract_v3` | No3d Asset Manager v3 | Asset Developer | `NO3D Dev` | 20 | Parent of Stowaway Inspector. |
| Yes | `NO3D_PT_stowaway_inspector` | Stowaway Inspector | Asset Developer | `NO3D Dev` | 30 | Keep beneath Asset Manager. |
| Yes | `NO3D_PT_dev_notes` | Dev Notes | Asset Developer | `NO3D Dev` | 40 | Development notes and handoff. |
| Yes | `NO3D_WIP_PT_feature_wip_tools` | WIP Tools | Asset Developer | `NO3D Dev` | 50 | Detach from Toolbox locally and register as a destination root; restore its original parent on router teardown. |
| Yes | `NO3D_CAD_PT_wip` | No3d CAD.wip | CAD WIP | `NO3D Dev` | 60 | Experimental local modeling. |
| Out of scope | `SENDNODES_PT_panel` | Send Nodes | Send Nodes | `Node Editor / Send Nodes` | — | This is a Node Editor sidebar panel, not a 3D View panel; Power Panel does not move panels between editor types. |

### Agent — live agent connection and handoff

| Enabled | Panel class ID | Current label | Source | Destination | Order | Notes |
| --- | --- | --- | --- | --- | ---: | --- |
| No change | `AGENT_BRIDGE_PT_panel` | Agent Bridge | Agent Bridge | `Agent` | 10 | Keep Agent Bridge immediately outside NO3D Dev as its own high-frequency tab. |

### NO3D Create — everyday viewport creation

| Enabled | Panel class ID | Current label | Source | Destination | Order | Notes |
| --- | --- | --- | --- | --- | ---: | --- |
| Yes | `NO3D_WIP_PT_toolbox` | Toolbox | Asset Developer | `NO3D Create` | 10 | General creation tools. |
| Yes | `NO3D_WIP_PT_feature_view_align` | View Align | Asset Developer | `NO3D Create` | 20 | Keep under Toolbox. |
| Yes | `NO3D_PT_paste_clipboard` | Paste Clipboard as Plane | Asset Developer | `NO3D Create` | 30 | Image/clipboard creation. |
| Yes | `NO3D_PT_aspect_overlay` | Aspect Overlay | Asset Developer | `NO3D Create` | 40 | View composition. |
| Yes | `VIEW3D_PT_make_mesh_camera_3d` | Camera Framing | Camera Utilities | `NO3D Create` | 50 | Primary camera framing workflow. |
| Yes | `VIEW3D_PT_make_mesh_camera_2d` | Selected Mesh Fit | Camera Utilities | `NO3D Create` | 60 | Secondary orthographic workflow. |

### NO3D Capture — images, renders, and media

| Enabled | Panel class ID | Current label | Source | Destination | Order | Notes |
| --- | --- | --- | --- | --- | ---: | --- |
| Yes | `NO3D_PT_viewport_screenshot` | Viewport Screenshot | Asset Developer | `NO3D Capture` | 10 | 3D View capture. |
| Yes | `NO3D_PT_editor_screenshot` | Editor Screenshot | Asset Developer | `NO3D Capture` | 20 | Non-viewport editor capture. |
| Yes | `NO3D_AD_PT_transparent_media` | Transparent Media | Asset Developer | `NO3D Capture` | 30 | Transparent still/video output. |
| Yes | `VIEW3D_PT_make_mesh_camera_render` | Mesh Camera Render | Camera Utilities | `NO3D Capture` | 40 | Camera-based output. |

### No3D Tools — public product workflows

| Enabled | Panel class ID | Current label | Source | Destination | Order | Notes |
| --- | --- | --- | --- | --- | ---: | --- |
| No change | `NO3D_PT_link_panel` | No3D Tools | No3D Tools | `No3D Tools` | 10 | Existing category. |
| No change | `NO3D_PT_print_panel` | Print Pipeline | No3D Tools | `No3D Tools` | 20 | Its registered children follow it. |
| No change | `NO3D_PT_send_actions` | Send | No3D Tools | `No3D Tools` | 90 | Keep final. |

### Eyecones — product-specific operation

| Enabled | Panel selector | Current contents | Source | Destination | Order | Notes |
| --- | --- | --- | --- | --- | ---: | --- |
| No change | `NO3DPIPE_PT_*` | Data Pipe, Transport, OSC, Spotify, displays, timelapse | Data Pipe | `Eyecones` | 10 | Preserve the existing product-specific tab. |

## Exact-name normalization

Before routing, normalize these legacy category strings:

| Encountered | Canonical |
| --- | --- |
| `No3D Dev` | `NO3D Dev` |
| `Claude` | `Agent` through `AGENT_BRIDGE_PT_panel` |
| `Agent` | `Agent` |

## Runtime contract

1. Snapshot each matched panel's original category, order, and parent ID.
2. Resolve all matched parents and children before mutating registration.
3. Unregister affected children before parents.
4. Apply configured destination, order, and any explicit parent detachment.
5. Register parents before children.
6. Reapply global category ordering.
7. Read back the live category inventory and report skipped routes.
8. On disable/unregister, restore the snapshot rather than guessing defaults.
9. Never save Blender user preferences as part of routing.

## Revision notes

- **Revision 3:** Implemented the executable route table in Power Panel,
  corrected the WIP Tools ID, documented Send Nodes as Node Editor scope, and
  added reversible category/order/parent snapshots.
- **Revision 2:** Restored Agent Bridge as its own `Agent` tab immediately
  after `NO3D Dev`; `Claude` is retained only as a search/legacy alias.
- **Revision 1:** Initial intent-based draft from the 2026-08-31 live panel
  inventory. Send Nodes class ID remains to be confirmed in a live enabled
  instance.
