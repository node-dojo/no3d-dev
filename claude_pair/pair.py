# SPDX-License-Identifier: GPL-3.0-or-later
"""
Pair-creation logic: port allocation, official MCP add-on control, iTerm2 spawn.
"""

__all__ = (
    "OFFICIAL_MCP_PKG_CANDIDATES",
    "find_free_port",
    "official_mcp_prefs",
    "is_official_mcp_running",
    "start_official_mcp_on_port",
    "stop_official_mcp",
    "spawn_iterm_paired",
    "reveal_iterm_window",
    "agentic_layout",
    "format_pair_label",
)

import socket
import subprocess
from pathlib import Path

import bpy

# Possible package keys for the official Blender Lab MCP add-on across install styles.
# Extension installs key under "bl_ext.<repo>.<id>"; legacy installs use the bare id.
OFFICIAL_MCP_PKG_CANDIDATES = (
    "bl_ext.lab_blender_org.mcp",
    "bl_ext.blender_org.mcp",
    "bl_ext.user_default.mcp",
    "mcp",
)

PAIR_PORT_BASE = 9876
PAIR_PORT_MAX = 9999


def find_free_port(start: int = PAIR_PORT_BASE, end: int = PAIR_PORT_MAX, host: str = "localhost") -> int:
    """Return the first port in [start, end] that nothing is listening on."""
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
    """Find the official MCP add-on's preferences object, regardless of how it was installed."""
    addons = bpy.context.preferences.addons
    for key in OFFICIAL_MCP_PKG_CANDIDATES:
        if key in addons:
            return addons[key].preferences
    # Fuzzy fallback: any addon key ending in ".mcp" exposed by Blender Lab.
    for key in addons.keys():
        if key.endswith(".mcp") or key == "mcp":
            return addons[key].preferences
    raise RuntimeError(
        "Official Blender MCP add-on not found. Install it from the Blender Lab "
        "extensions repository (https://lab.blender.org/) and enable it."
    )


def is_official_mcp_running() -> bool:
    """Best-effort detection: try to import the running server module."""
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
    """Configure prefs (in-process only) and start the official MCP server."""
    prefs = official_mcp_prefs()
    if is_official_mcp_running():
        bpy.ops.blmcp.server_stop()
    prefs.host = host
    prefs.port = port
    result = bpy.ops.blmcp.server_start()
    if "FINISHED" not in result:
        raise RuntimeError(f"Failed to start MCP server on {host}:{port} (result={result})")


def stop_official_mcp() -> None:
    if is_official_mcp_running():
        bpy.ops.blmcp.server_stop()


def format_pair_label(blendfile_stem: str, port: int, blender_pid: int) -> str:
    """Single source of truth for the pair identifier used in titles + registry."""
    return f"{blendfile_stem} :{port} (pid{blender_pid})"


def _shell_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def _applescript_quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def spawn_iterm_paired(
    *,
    cwd: Path,
    port: int,
    title: str,
    blender_pid: int,
    claude_command: str = "claude",
    claude_extra_args: str = "",
    claude_auto_start: bool = True,
    open_as: str = "WINDOW",
    profile: str = "",
    session_id: str = "",
    resume_session_id: str = "",
) -> str:
    """
    Open a new iTerm2 window/tab, set its title, cd to cwd, export
    BLENDER_MCP_PORT, and (optionally) run claude. Returns the iTerm2 window id (string).

    If `session_id` is set, the claude command will be launched with
    `--session-id <uuid>` so it adopts the given UUID for a NEW session.
    If `resume_session_id` is set, the claude command will be launched with
    `--resume <uuid>` to re-attach an existing transcript. `session_id` and
    `resume_session_id` are mutually exclusive; `resume_session_id` wins if both.
    """
    cwd_q = _shell_quote(str(cwd))
    parts = [
        f"cd {cwd_q}",
        f"export BLENDER_MCP_PORT={port}",
        f"export BLENDER_PAIR_PID={blender_pid}",
        f"echo 'Paired with Blender pid {blender_pid} on port {port}.'",
    ]
    if claude_auto_start:
        cmd = claude_command.strip()
        global_ctx = Path.home() / ".claude-pair" / "global-context.md"
        if global_ctx.exists():
            cmd = f'{cmd} --append-system-prompt "$(cat {_shell_quote(str(global_ctx))})"'
        # Session flags. `--resume` takes precedence over `--session-id` when both
        # are supplied (resume is the explicit user intent in that case).
        if resume_session_id.strip():
            cmd = f"{cmd} --resume {_shell_quote(resume_session_id.strip())}"
        elif session_id.strip():
            cmd = f"{cmd} --session-id {_shell_quote(session_id.strip())}"
        if claude_extra_args.strip():
            cmd = f"{cmd} {claude_extra_args.strip()}"
        parts.append(cmd)
    setup_cmd = " && ".join(parts)

    profile_clause = (
        f"with profile {_applescript_quote(profile)}"
        if profile.strip()
        else "with default profile"
    )

    if open_as == "TAB":
        script = f'''
tell application "iTerm"
    activate
    if (count of windows) is 0 then
        set targetWindow to (create window {profile_clause})
    else
        set targetWindow to current window
        tell targetWindow to create tab {profile_clause}
    end if
    set wid to id of targetWindow
    tell targetWindow
        tell current session
            set name to {_applescript_quote(title)}
            write text {_applescript_quote(setup_cmd)}
        end tell
    end tell
    return wid as string
end tell
'''
    else:
        script = f'''
tell application "iTerm"
    activate
    set newWindow to (create window {profile_clause})
    tell newWindow
        set wid to id
        tell current session
            set name to {_applescript_quote(title)}
            write text {_applescript_quote(setup_cmd)}
        end tell
    end tell
    return wid as string
end tell
'''
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def reveal_iterm_window(window_id: str) -> bool:
    """Bring the given iTerm2 window forward. Returns True on success."""
    if not window_id:
        return False
    script = f'''
tell application "iTerm"
    repeat with w in windows
        if (id of w as string) is equal to {_applescript_quote(window_id)} then
            activate
            select w
            return "ok"
        end if
    end repeat
    return "missing"
end tell
'''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip() == "ok"
    except subprocess.CalledProcessError:
        return False


def agentic_layout(iterm_window_id: str, blender_pid: int) -> tuple[bool, str]:
    """
    Tile Blender on the left and the paired iTerm window on the right of the
    main display, preserving the current Blender:iTerm width ratio.

    Returns (ok, message).
    """
    if not iterm_window_id:
        return False, "No iTerm window id recorded for this pair."

    # Screen-bounds via NSScreen (AppleScriptObjC). `Finder`/`System Events` `bounds of
    # desktop` is unreliable on recent macOS — it errors with -1728 on multi-display setups.
    # NSScreen returns Cocoa coords (origin bottom-left); we convert to the Carbon top-left
    # coords used by System Events window positioning. visibleFrame excludes menu bar/dock.
    script = f'''
use framework "AppKit"

tell application "System Events"
    -- Prefer addressing by PID so multi-Blender setups stay correct, but fall back to
    -- by-name if the PID lookup reports no windows (some macOS Accessibility paths only
    -- enumerate windows when the process is addressed by name).
    set blenderProcs to (every process whose unix id is {blender_pid})
    if blenderProcs is {{}} then
        return "missing_blender"
    end if
    set blenderProc to item 1 of blenderProcs
    if (count of windows of blenderProc) is 0 then
        try
            set blenderProc to process "Blender"
        end try
    end if
    if (count of windows of blenderProc) is 0 then
        return "no_blender_window"
    end if
    set blenderWin to window 1 of blenderProc
    set bPos to position of blenderWin
    set bSize to size of blenderWin
    set bx to item 1 of bPos
    set byPos to item 2 of bPos
    set bWidth to item 1 of bSize
    set bHeight to item 2 of bSize
end tell

tell application "iTerm"
    set found to false
    repeat with w in windows
        if (id of w as string) is equal to {_applescript_quote(iterm_window_id)} then
            set targetWin to w
            set found to true
            exit repeat
        end if
    end repeat
    if not found then
        return "missing_iterm"
    end if
    set iBounds to bounds of targetWin
    set iWidth to (item 3 of iBounds) - (item 1 of iBounds)
end tell

set scrs to (current application's NSScreen's screens())
set primaryFrame to (item 1 of scrs)'s frame()
set primaryH to (item 2 of (item 2 of primaryFrame))

set bestSX to missing value
set bestSY to missing value
set bestSW to missing value
set bestSH to missing value
set bcx to bx + (bWidth / 2)
set bcy to byPos + (bHeight / 2)
repeat with s in scrs
    set vf to s's visibleFrame()
    set sox to (item 1 of (item 1 of vf))
    set soy to (item 2 of (item 1 of vf))
    set sw to (item 1 of (item 2 of vf))
    set sh to (item 2 of (item 2 of vf))
    set sCarbonY to primaryH - (soy + sh)
    set sCarbonX to sox
    if (bcx >= sCarbonX) and (bcx < sCarbonX + sw) and (bcy >= sCarbonY) and (bcy < sCarbonY + sh) then
        set bestSX to sCarbonX as integer
        set bestSY to sCarbonY as integer
        set bestSW to sw as integer
        set bestSH to sh as integer
        exit repeat
    end if
end repeat
if bestSX is missing value then
    -- Fallback: use the primary screen's visible frame.
    set pvf to (item 1 of scrs)'s visibleFrame()
    set bestSX to (item 1 of (item 1 of pvf)) as integer
    set bestSW to (item 1 of (item 2 of pvf)) as integer
    set bestSH to (item 2 of (item 2 of pvf)) as integer
    set bestSY to (primaryH - ((item 2 of (item 1 of pvf)) + bestSH)) as integer
end if

set totalW to bWidth + iWidth
if totalW is less than or equal to 0 then
    set ratio to 0.6
else
    set ratio to bWidth / totalW
end if
if ratio < 0.15 then set ratio to 0.15
if ratio > 0.85 then set ratio to 0.85

set lw to ((bestSW * ratio) as integer)
set splitX to bestSX + lw
set rw to bestSW - lw

tell application "System Events"
    set position of blenderWin to {{bestSX, bestSY}}
    set size of blenderWin to {{lw, bestSH}}
end tell

tell application "iTerm"
    set bounds of targetWin to {{splitX, bestSY, splitX + rw, bestSY + bestSH}}
    activate
end tell

tell application "System Events"
    set frontmost of blenderProc to true
end tell

return "ok"
'''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, check=True,
        )
        out = result.stdout.strip()
        if out == "ok":
            return True, "Tiled Blender (left) and iTerm (right)."
        if out == "missing_blender":
            return False, f"Could not find Blender process (pid {blender_pid})."
        if out == "no_blender_window":
            return False, "Blender process has no visible window."
        if out == "missing_iterm":
            return False, "Could not find the paired iTerm window (was it closed?)."
        return False, f"AppleScript returned: {out!r}"
    except subprocess.CalledProcessError as ex:
        return False, f"osascript failed: {ex.stderr.strip() or ex}"
