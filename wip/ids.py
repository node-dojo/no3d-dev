"""Single source of truth for every user-visible / registered name in this add-on.

No other module may hardcode these strings. A rename is a one-file edit here.
"""

ADDON_NAME = "No3d Wip"
ADDON_PACKAGE = __package__  # "no3d_tools_wip"

# N-panel — nests the WIP Toolbox under the Asset Developer's "No3D Dev" tab
# (retargeted from the standalone add-on's "NO3D WIP" tab on merge).
NPANEL_CATEGORY = "No3D Dev"

# Sections (each WIP feature gets its own section / panel idname here)
TOOLBOX_PANEL_IDNAME = "NO3D_WIP_PT_toolbox"
TOOLBOX_PANEL_LABEL = "Toolbox"

# View Align — view-relative directional align (verts in edit mode, objects in object mode)
VIEW_ALIGN_OT_IDNAME = "no3d_wip.view_align"
VIEW_ALIGN_OT_LABEL = "View Align"
VIEW_ALIGN_PIE_IDNAME = "NO3D_WIP_MT_view_align_pie"
VIEW_ALIGN_PIE_LABEL = "View Align"

# Direction property values (shared by the operator enum and the pie buttons)
DIR_LEFT = "LEFT"
DIR_RIGHT = "RIGHT"
DIR_TOP = "TOP"
DIR_BOTTOM = "BOTTOM"
DIR_CENTER = "CENTER"

# WIP Tools — Make Spin WIP (moved here from No3d Asset Manager)
WIP_TOOLS_PANEL_LABEL = "WIP Tools"
MAKE_SPIN_OT_IDNAME = "no3d_wip.make_spin"
MAKE_SPIN_OT_LABEL = "Make Spin WIP"
PUBLISH_MAKE_SPIN_OT_IDNAME = "no3d_wip.publish_make_spin"
PUBLISH_MAKE_SPIN_OT_LABEL = "Publish make spin to Library"
MAKE_SPIN_GROUP = "make spin"  # GN node group name (single source of truth)

# ---------------------------------------------------------------------------
# Feature registry — the single source of truth for the prefs feature table and
# the per-feature N-panel sub-sections. Add a feature here once; both the
# preferences table and the Toolbox sub-panels pick it up automatically.
#
# Each entry:
#   id        — stable key (also the per-feature N-panel sub-panel suffix)
#   name      — user-facing feature name
#   version   — feature-local semver string (independent of the add-on version)
#   updated   — date/time of last update, "YYYY-MM-DD HH:MM" (hand-maintained)
#   icon      — Blender icon id used in the prefs table / sub-panel header
#   panel_id  — idname of the N-panel sub-panel that surfaces this feature
# Bump `version` + `updated` by hand whenever the feature's behavior changes.
# ---------------------------------------------------------------------------

VIEW_ALIGN_SUBPANEL_IDNAME = "NO3D_WIP_PT_feature_view_align"
WIP_TOOLS_SUBPANEL_IDNAME = "NO3D_WIP_PT_feature_wip_tools"

FEATURES = (
    {
        "id": "view_align",
        "name": VIEW_ALIGN_PIE_LABEL,
        "version": "0.1.0",
        "updated": "2026-06-16 00:00",
        "icon": "MOD_MIRROR",
        "panel_id": VIEW_ALIGN_SUBPANEL_IDNAME,
    },
    {
        "id": "wip_tools",
        "name": WIP_TOOLS_PANEL_LABEL,
        "version": "0.1.0",
        "updated": "2026-06-16 14:42",
        "icon": "TOOL_SETTINGS",
        "panel_id": WIP_TOOLS_SUBPANEL_IDNAME,
    },
)
