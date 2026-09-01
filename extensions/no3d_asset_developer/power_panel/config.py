"""Executable configuration for the No3d Power Panel feature suite."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Route:
    category: str
    order: int
    detach_parent: bool = False


DESTINATION_ORDER = (
    "NO3D Dev",
    "Agent",
    "NO3D Create",
    "NO3D Capture",
    "No3D Tools",
    "Eyecones",
)

DEFAULT_SLOTS = {
    1: "NO3D Dev",
    2: "NO3D Create",
    3: "NO3D Capture",
    4: "No3D Tools",
    5: "Agent",
    6: "",
    7: "",
    8: "",
    9: "",
}

CATEGORY_ALIASES = {
    "NO3D Dev": (
        "no3d dev", "asset manager", "development", "wip", "cad",
    ),
    "Agent": (
        "agent", "agent bridge", "claude", "serve to agents",
    ),
    "NO3D Create": (
        "create", "clipboard", "align", "aspect", "camera framing", "mesh fit",
    ),
    "NO3D Capture": (
        "capture", "screenshot", "render", "transparent media",
    ),
    "No3D Tools": (
        "no3d tools", "print", "printer", "output", "multipart", "send",
    ),
    "Eyecones": (
        "eyecones", "data pipe", "transport", "osc", "spotify", "timelapse",
        "window screens",
    ),
}

DESTINATION_LABELS = {
    "Agent": "Agent Bridge",
}

# Exact registered panel IDs are the stable selectors. Missing extensions are
# skipped; descendants follow their explicitly routed parents unless they have
# their own route.
PANEL_ROUTES = {
    "NO3D_PT_extract_v3": Route("NO3D Dev", 20),
    "NO3D_PT_stowaway_inspector": Route("NO3D Dev", 30),
    "NO3D_PT_dev_notes": Route("NO3D Dev", 40),
    "NO3D_WIP_PT_feature_wip_tools": Route("NO3D Dev", 50, True),
    "NO3D_CAD_PT_wip": Route("NO3D Dev", 60),
    "NO3D_WIP_PT_toolbox": Route("NO3D Create", 10),
    "NO3D_WIP_PT_feature_view_align": Route("NO3D Create", 20),
    "NO3D_PT_paste_clipboard": Route("NO3D Create", 30),
    "NO3D_PT_aspect_overlay": Route("NO3D Create", 40),
    "VIEW3D_PT_make_mesh_camera_3d": Route("NO3D Create", 50),
    "VIEW3D_PT_make_mesh_camera_2d": Route("NO3D Create", 60),
    "NO3D_PT_viewport_screenshot": Route("NO3D Capture", 10),
    "NO3D_PT_editor_screenshot": Route("NO3D Capture", 20),
    "NO3D_AD_PT_transparent_media": Route("NO3D Capture", 30),
    "VIEW3D_PT_make_mesh_camera_render": Route("NO3D Capture", 40),
    "AGENT_BRIDGE_PT_panel": Route("Agent", 10),
}

# Blender's menu_pie call order: West, East, South, North, Northwest,
# Northeast, Southwest, Southeast.
PIE_DIRECTIONS = (
    ("WEST", "slot", 1, "NO3D Dev"),
    ("EAST", "slot", 4, "No3D Tools"),
    ("SOUTH", "slot", 3, "NO3D Capture"),
    ("NORTH", "slot", 2, "NO3D Create"),
    ("NORTHWEST", "slot", 5, "Agent Bridge"),
    ("NORTHEAST", "search", 0, "Search All Tabs"),
    ("SOUTHWEST", "toggle", 0, "Toggle Sidebar"),
    ("SOUTHEAST", "previous", 0, "Last Used Tab"),
)

SLOT_PROPERTY_PREFIX = "power_panel_slot_"
