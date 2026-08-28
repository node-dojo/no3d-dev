# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent Bridge's own port allocation + official Blender MCP add-on control.

bpy and the official MCP add-on are imported lazily inside functions so this
module imports cleanly outside Blender (the package __init__ imports it via the
_HAS_BPY guard; tests never call these functions)."""

import socket

PORT_BASE = 9876
PORT_MAX = 9999

# Package keys the official Blender MCP add-on may be installed under.
OFFICIAL_MCP_PKG_CANDIDATES = (
    "bl_ext.lab_blender_org.mcp",
    "bl_ext.blender_org.mcp",
    "bl_ext.user_default.mcp",
    "mcp",
)


def find_free_port(start: int = PORT_BASE, end: int = PORT_MAX, host: str = "localhost") -> int:
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.1)
            try:
                s.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"No free port in {start}-{end}")


def official_mcp_prefs():
    import bpy
    addons = bpy.context.preferences.addons
    for key in OFFICIAL_MCP_PKG_CANDIDATES:
        if key in addons:
            return addons[key].preferences
    for key in addons.keys():
        if key.endswith(".mcp") or key == "mcp":
            return addons[key].preferences
    raise RuntimeError(
        "Official Blender MCP add-on not found. Install it from the Blender Lab "
        "extensions repository and enable it."
    )


def is_official_mcp_running() -> bool:
    try:
        from bl_ext.lab_blender_org.mcp import mcp_to_blender_server  # type: ignore
        return mcp_to_blender_server.is_running()
    except (ImportError, AttributeError):
        pass
    try:
        from mcp import mcp_to_blender_server  # type: ignore
        return mcp_to_blender_server.is_running()
    except (ImportError, AttributeError):
        return False


def start_official_mcp_on_port(port: int, host: str = "localhost") -> None:
    import bpy
    prefs = official_mcp_prefs()
    if is_official_mcp_running():
        bpy.ops.blmcp.server_stop()
    prefs.host = host
    prefs.port = port
    result = bpy.ops.blmcp.server_start()
    if "FINISHED" not in result:
        raise RuntimeError(f"Failed to start MCP server on {host}:{port} (result={result})")


def stop_official_mcp() -> None:
    import bpy
    if is_official_mcp_running():
        bpy.ops.blmcp.server_stop()
