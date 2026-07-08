# SPDX-License-Identifier: GPL-3.0-or-later
"""
Claude Pair — pair this Blender instance with a Claude Code terminal session.

The pairing flow:
  1. Pick a free TCP port starting at 9876.
  2. Configure the official Blender MCP add-on's prefs to that port (in-process only — never saved).
  3. Start the official MCP bridge server.
  4. Open an iTerm2 window with cwd = blend file dir, BLENDER_MCP_PORT env var set, claude running.
  5. Record the pair in ~/.blender-pairs/<blender-pid>.json.
"""

__all__ = ("register", "unregister")

import atexit
import json
import os
import subprocess
import uuid
from pathlib import Path

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Operator, Panel

# Scene custom-property key for the per-.blend Claude session UUID.
# Centralized so renames are a one-file edit (CLAUDE.md core rule #3).
SESSION_ID_KEY = "claude_pair_session_id"

VAULT_GLOBAL_DOC = Path(
    "/Users/joebowers/Library/Mobile Documents/iCloud~md~obsidian/Documents/Vault_001/Agent/Blender and Claude workflow.md"
)
GLOBAL_POINTER_DOC = Path.home() / ".claude-pair" / "global-context.md"

GLOBAL_POINTER_TEMPLATE = """# Blender Pair — global context

You are running in a Claude Code session paired with a specific Blender instance via the Claude Pair add-on. The Blender MCP server is bound on `localhost:$BLENDER_MCP_PORT` (this env var is set in your shell). Tools are available under the `blender` MCP namespace (e.g. `mcp__blender__execute_blender_code`).

## Authoritative workflow doc

The global Blender + Claude workflow guide lives at:

  `/Users/joebowers/Library/Mobile Documents/iCloud~md~obsidian/Documents/Vault_001/Agent/Blender and Claude workflow.md`

Read it for cross-project conventions. Keep edits there, not here.

## Per-project notes

If a `CLAUDE.md` file exists in this session's working directory, it loads automatically and overrides anything here for that project.
"""

PROJECT_MD_TEMPLATE = """# CLAUDE.md — project notes

Project-specific guidance for Claude in this folder. This file overrides the
global Blender workflow doc for this project. Edit freely.
"""

PROJECT_PERMISSIONS_PAYLOAD = {
    "permissions": {
        "allow": [
            "mcp__blender__*",
            "Bash(blender-manage pairs*)",
            "Read(*)",
            "Glob(*)",
            "Grep(*)",
        ]
    }
}

from . import pair as pair_mod
from . import registry as registry_mod

_BLENDER_PID = os.getpid()
_KEYMAPS: list = []


HOST_PACKAGE = __package__.rsplit(".", 1)[0]  # host add-on package, e.g. "no3d_asset_developer"


def _prefs():
    return bpy.context.preferences.addons[HOST_PACKAGE].preferences


# ─── Pair-state helpers ─────────────────────────────────────────────────────────

def _current_pair() -> dict | None:
    return registry_mod.read(_BLENDER_PID)


def _blendfile_path() -> Path | None:
    fp = bpy.data.filepath
    return Path(fp) if fp else None


def _resolve_project_cwd() -> Path | None:
    """Cwd of the active pair, else the blend file's dir if saved, else None."""
    entry = _current_pair()
    if entry:
        cwd = entry.get("cwd")
        if cwd:
            return Path(cwd)
    blendfile = _blendfile_path()
    if blendfile is not None:
        return blendfile.parent
    return None


def _write_project_permissions(cwd: Path) -> tuple[bool, str]:
    """Write .claude/settings.local.json into cwd if absent. Returns (wrote, message)."""
    settings_path = cwd / ".claude" / "settings.local.json"
    if settings_path.exists():
        return False, f"Skipped (already exists): {settings_path}"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(PROJECT_PERMISSIONS_PAYLOAD, indent=2) + "\n")
    return True, f"Wrote {settings_path}"


# ─── Session-ID (per-.blend) helpers ───────────────────────────────────────────
#
# The session ID lives as a scene custom property so it persists in the .blend.
# We attach it to `bpy.context.scene` (the active scene) — keeping the contract
# simple: one .blend, one session. If the user uses multiple scenes, the active
# scene at pair-time owns the ID. This matches the spec ("scene custom property").

def _stored_session_id() -> str:
    """Return the UUID stored on the active scene, or '' if none."""
    try:
        scene = bpy.context.scene
    except AttributeError:
        return ""
    if scene is None:
        return ""
    val = scene.get(SESSION_ID_KEY, "")
    return str(val) if val else ""


def _set_session_id(session_id: str) -> None:
    """Write the UUID to the active scene's custom properties."""
    scene = bpy.context.scene
    if scene is None:
        return
    scene[SESSION_ID_KEY] = session_id


def _clear_session_id() -> None:
    scene = bpy.context.scene
    if scene is None:
        return
    if SESSION_ID_KEY in scene:
        del scene[SESSION_ID_KEY]


def _mint_session_id() -> str:
    """Mint a fresh UUID4 string for a new Claude session."""
    return str(uuid.uuid4())


# ─── Operators ──────────────────────────────────────────────────────────────────

class CLAUDE_PAIR_OT_pair_now(Operator):
    bl_idname = "claude_pair.pair_now"
    bl_label = "Pair Now"
    bl_description = "Open a paired iTerm2 + Claude session bound to this Blender instance"
    bl_options = {"REGISTER"}

    # Set by the dialog draw() / invoke() flow.
    save_before_pairing: bpy.props.BoolProperty(  # type: ignore[valid-type]
        name="Save & pair",
        description="Save the .blend before pairing (required to persist the session ID)",
        default=True,
    )

    # When True, the operator runs `--resume <stored-uuid>` instead of `--session-id`.
    # Set by CLAUDE_PAIR_OT_repair_resume before invoking pair_now via call_operator.
    # We use a hidden property rather than a separate code path because all the
    # other pairing setup (port, MCP start, iTerm spawn, registry write) is identical.
    resume_existing: bpy.props.BoolProperty(  # type: ignore[valid-type]
        name="Resume existing",
        description="Internal: launch claude with --resume <stored-uuid> instead of minting a new ID",
        default=False,
        options={"HIDDEN", "SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        del context
        return _current_pair() is None

    def invoke(self, context, event):
        del event
        # Unsaved-file paths:
        #  - .blend never saved (no filepath): refuse — session ID can't persist.
        #    The handoff spec is explicit: "Refuse to pair if the .blend has never been saved."
        #  - .blend saved before but is_dirty: show a "Save & pair / Cancel" dialog.
        blendfile = _blendfile_path()
        if blendfile is None:
            self.report(
                {"ERROR"},
                "Save the .blend file before pairing — the session ID is tied to this file.",
            )
            return {"CANCELLED"}
        if bpy.data.is_dirty:
            return context.window_manager.invoke_props_dialog(self, width=420)
        return self.execute(context)

    def draw(self, context):
        del context
        layout = self.layout
        layout.label(text="This .blend has unsaved changes.", icon="ERROR")
        layout.label(text="Pairing stores a session ID in the .blend, so we need to save.")
        layout.prop(self, "save_before_pairing")
        layout.label(
            text="Uncheck and OK to cancel pairing instead.",
            icon="INFO",
        )

    def execute(self, context):
        del context
        prefs = _prefs()

        # Reject the no-filepath case defensively in case execute() is called directly
        # (e.g. from a script) skipping invoke()'s gate.
        blendfile = _blendfile_path()
        if blendfile is None:
            self.report(
                {"ERROR"},
                "Save the .blend file before pairing — the session ID is tied to this file.",
            )
            return {"CANCELLED"}

        # Honour the dialog's save-or-cancel choice.
        if bpy.data.is_dirty:
            if not self.save_before_pairing:
                self.report({"WARNING"}, "Pairing cancelled (file not saved).")
                return {"CANCELLED"}
            try:
                bpy.ops.wm.save_mainfile()
            except RuntimeError as ex:
                self.report({"ERROR"}, f"Save failed: {ex}")
                return {"CANCELLED"}

        cwd = blendfile.parent

        # Session-ID gating:
        #  - Resume mode: require a stored UUID, use it with --resume.
        #  - Pair mode: reuse stored UUID if present (idempotent re-pair without
        #    forcing "New session"); otherwise mint a fresh one and persist it.
        stored = _stored_session_id()
        if self.resume_existing:
            if not stored:
                self.report(
                    {"ERROR"},
                    "No stored session ID for this .blend. Use 'Pair Now' first.",
                )
                return {"CANCELLED"}
            session_id_for_new = ""
            resume_session_id = stored
        else:
            if not stored:
                stored = _mint_session_id()
                _set_session_id(stored)
                # Persist the freshly-minted ID immediately so a crash before the
                # first save still keeps it. We already saved above if dirty, but
                # setting the custom prop marks the file dirty again.
                try:
                    bpy.ops.wm.save_mainfile()
                except RuntimeError as ex:
                    self.report({"ERROR"}, f"Save after minting session ID failed: {ex}")
                    return {"CANCELLED"}
            session_id_for_new = stored
            resume_session_id = ""

        try:
            port = pair_mod.find_free_port(
                start=prefs.port_range_start,
                end=prefs.port_range_end,
                host=prefs.mcp_host,
            )
        except RuntimeError as ex:
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}

        try:
            pair_mod.start_official_mcp_on_port(port, host=prefs.mcp_host)
        except Exception as ex:  # pylint: disable=broad-exception-caught
            self.report({"ERROR"}, f"MCP start failed: {ex}")
            return {"CANCELLED"}

        stem = blendfile.stem
        title = pair_mod.format_pair_label(stem, port, _BLENDER_PID)

        try:
            window_id = pair_mod.spawn_iterm_paired(
                cwd=cwd,
                port=port,
                title=title,
                blender_pid=_BLENDER_PID,
                claude_command=prefs.claude_command,
                claude_extra_args=prefs.claude_extra_args,
                claude_auto_start=prefs.claude_auto_start,
                open_as=prefs.iterm_open_as,
                profile=prefs.iterm_profile,
                session_id=session_id_for_new,
                resume_session_id=resume_session_id,
            )
        except Exception as ex:  # pylint: disable=broad-exception-caught
            pair_mod.stop_official_mcp()
            self.report({"ERROR"}, f"iTerm2 spawn failed: {ex}")
            return {"CANCELLED"}

        registry_mod.write(_BLENDER_PID, {
            "port": port,
            "host": prefs.mcp_host,
            "blendfile": str(blendfile),
            "cwd": str(cwd),
            "iterm_window_id": window_id,
            "title": title,
            "session_id": stored,
            "resumed": bool(self.resume_existing),
        })
        if prefs.auto_write_permissions:
            try:
                wrote, msg = _write_project_permissions(cwd)
                if prefs.verbose_logging:
                    print(f"[claude_pair] permissions: {msg}")
            except Exception as ex:  # pylint: disable=broad-exception-caught
                if prefs.verbose_logging:
                    print(f"[claude_pair] permissions write failed: {ex}")
        if prefs.verbose_logging:
            mode = "resumed" if self.resume_existing else "new"
            print(
                f"[claude_pair] paired pid={_BLENDER_PID} port={port} "
                f"title={title!r} session={stored} mode={mode}"
            )
        verb = "Resumed" if self.resume_existing else "Paired"
        self.report({"INFO"}, f"{verb}: {title}")
        return {"FINISHED"}


class CLAUDE_PAIR_OT_repair_resume(Operator):
    """Re-attach to the .blend's stored Claude session after a Blender restart."""
    bl_idname = "claude_pair.repair_resume"
    bl_label = "Re-pair & Resume"
    bl_description = (
        "Restart the MCP server (if needed) and launch claude --resume <stored-uuid> "
        "to re-attach the prior conversation for this .blend"
    )
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        del context
        # Available only when there is no current pair AND a stored session ID exists.
        # If there's already an active pair, the user should use Unpair first.
        return _current_pair() is None and bool(_stored_session_id())

    def execute(self, context):
        del context
        prefs = _prefs()
        stored = _stored_session_id()
        if not stored:
            self.report(
                {"ERROR"},
                "No paired session found for this .blend. Use 'Pair Now' first.",
            )
            return {"CANCELLED"}
        blendfile = _blendfile_path()
        if blendfile is None:
            self.report(
                {"ERROR"},
                "Save the .blend file first — the resume target is tied to the file path.",
            )
            return {"CANCELLED"}

        # Open question #1 default: auto-start the MCP server if it isn't running.
        # Rationale: the whole point of this button is one-click restore. Forcing the
        # user to do a separate "start server" step would defeat that. The pair_now
        # operator is reused (with resume_existing=True) and it handles port + MCP
        # start as part of its normal flow.
        if prefs.verbose_logging:
            print(f"[claude_pair] re-pair & resume requested for session={stored}")
        bpy.ops.claude_pair.pair_now(resume_existing=True)  # type: ignore[attr-defined]
        return {"FINISHED"}


class CLAUDE_PAIR_OT_new_session_for_file(Operator):
    """Clear the stored session ID and pair fresh."""
    bl_idname = "claude_pair.new_session_for_file"
    bl_label = "New Session for this File"
    bl_description = (
        "Forget the stored Claude session ID for this .blend and start a fresh paired "
        "session. Use when the prior conversation is no longer useful."
    )
    bl_options = {"REGISTER"}

    confirm: BoolProperty(  # type: ignore[valid-type]
        name="Yes, start a new session",
        description="Confirm: the stored session ID will be cleared and a fresh one minted",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        del context
        # Available only when there is no current pair. (If a pair is live, unpair first.)
        return _current_pair() is None

    def invoke(self, context, event):
        del event
        # Confirmation dialog only if there's something to clear. If nothing's stored,
        # this is just equivalent to Pair Now — skip the prompt.
        if _stored_session_id():
            return context.window_manager.invoke_props_dialog(self, width=420)
        self.confirm = True
        return self.execute(context)

    def draw(self, context):
        del context
        layout = self.layout
        stored = _stored_session_id()
        layout.label(text="Start a new Claude session for this .blend?", icon="QUESTION")
        if stored:
            layout.label(text=f"Current stored ID: {stored}", icon="LINKED")
        layout.label(
            text="The old conversation will not be deleted — its UUID is just forgotten here.",
            icon="INFO",
        )
        layout.prop(self, "confirm")

    def execute(self, context):
        del context
        if not self.confirm:
            self.report({"WARNING"}, "Cancelled (not confirmed).")
            return {"CANCELLED"}
        _clear_session_id()
        # Save so the cleared state persists. If the file is unsaved (no filepath),
        # bpy.ops.wm.save_mainfile() will pop a file picker — but we already refused
        # to pair without a saved file, so this branch only fires for already-saved
        # blends.
        if _blendfile_path() is not None:
            try:
                bpy.ops.wm.save_mainfile()
            except RuntimeError as ex:
                self.report({"ERROR"}, f"Save after clearing session ID failed: {ex}")
                return {"CANCELLED"}
        # Now run a fresh Pair Now — it will mint a new UUID since the stored one is gone.
        bpy.ops.claude_pair.pair_now("INVOKE_DEFAULT")
        return {"FINISHED"}


class CLAUDE_PAIR_OT_reveal(Operator):
    bl_idname = "claude_pair.reveal"
    bl_label = "Reveal Terminal"
    bl_description = "Bring the paired iTerm2 window to the front"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        del context
        return _current_pair() is not None

    def execute(self, context):
        del context
        entry = _current_pair()
        if not entry:
            self.report({"ERROR"}, "No active pair.")
            return {"CANCELLED"}
        window_id = entry.get("iterm_window_id", "")
        if pair_mod.reveal_iterm_window(window_id):
            return {"FINISHED"}
        self.report({"WARNING"}, "Could not find the paired iTerm2 window (was it closed?).")
        return {"CANCELLED"}


class CLAUDE_PAIR_OT_agentic_layout(Operator):
    bl_idname = "claude_pair.agentic_layout"
    bl_label = "Agentic Layout"
    bl_description = (
        "Reveal the paired terminal, then tile Blender on the left and iTerm on "
        "the right using the current Blender:iTerm width ratio"
    )
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        del context
        return _current_pair() is not None

    def execute(self, context):
        del context
        entry = _current_pair()
        if not entry:
            self.report({"ERROR"}, "No active pair.")
            return {"CANCELLED"}
        window_id = entry.get("iterm_window_id", "")
        if not pair_mod.reveal_iterm_window(window_id):
            self.report({"WARNING"}, "Could not reveal the paired iTerm window (was it closed?).")
            return {"CANCELLED"}
        ok, msg = pair_mod.agentic_layout(window_id, _BLENDER_PID)
        if ok:
            self.report({"INFO"}, msg)
            return {"FINISHED"}
        self.report({"WARNING"}, msg)
        return {"CANCELLED"}


class CLAUDE_PAIR_OT_unpair(Operator):
    bl_idname = "claude_pair.unpair"
    bl_label = "Unpair"
    bl_description = "Stop the MCP server and forget this pair (does not close the terminal)"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        del context
        return _current_pair() is not None

    def execute(self, context):
        del context
        pair_mod.stop_official_mcp()
        registry_mod.remove(_BLENDER_PID)
        self.report({"INFO"}, "Unpaired.")
        return {"FINISHED"}


class CLAUDE_PAIR_OT_copy_diagnostics(Operator):
    bl_idname = "claude_pair.copy_diagnostics"
    bl_label = "Copy Diagnostics"
    bl_description = "Copy a diagnostic summary to the clipboard (paste into chat to share state)"
    bl_options = {"REGISTER"}

    def execute(self, context):
        import platform
        prefs = _prefs()
        entry = _current_pair()
        lines = [
            "=== Claude Pair diagnostics ===",
            f"blender_pid: {_BLENDER_PID}",
            f"blender_version: {bpy.app.version_string}",
            f"platform: {platform.platform()}",
            f"blendfile: {bpy.data.filepath or '(unsaved)'}",
            f"current_pair: {entry}",
            f"registry_dir: {registry_mod.REGISTRY_DIR}",
            f"prefs.mcp_host: {prefs.mcp_host}",
            f"prefs.port_range: {prefs.port_range_start}-{prefs.port_range_end}",
            f"prefs.iterm_open_as: {prefs.iterm_open_as}",
            f"prefs.iterm_profile: {prefs.iterm_profile or '(default)'}",
            f"prefs.claude_command: {prefs.claude_command}",
            f"prefs.claude_extra_args: {prefs.claude_extra_args}",
            f"prefs.claude_auto_start: {prefs.claude_auto_start}",
            f"prefs.scratch_dir: {prefs.scratch_dir}",
            f"prefs.start_server_on_load: {prefs.start_server_on_load}",
            f"stored_session_id: {_stored_session_id() or '(none)'}",
            f"official_mcp_running: {pair_mod.is_official_mcp_running()}",
        ]
        try:
            prefs_check = pair_mod.official_mcp_prefs()
            lines.append(f"official_mcp_addon_port: {prefs_check.port}")
            lines.append(f"official_mcp_addon_host: {prefs_check.host}")
        except Exception as ex:  # pylint: disable=broad-exception-caught
            lines.append(f"official_mcp_addon: NOT FOUND ({ex})")
        text = "\n".join(lines)
        context.window_manager.clipboard = text
        print(text)
        self.report({"INFO"}, "Diagnostics copied to clipboard.")
        return {"FINISHED"}


class CLAUDE_PAIR_OT_open_registry_dir(Operator):
    bl_idname = "claude_pair.open_registry_dir"
    bl_label = "Open Registry"
    bl_description = "Open ~/.blender-pairs/ in Finder"
    bl_options = {"REGISTER"}

    def execute(self, context):
        del context
        import subprocess
        registry_mod.REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["open", str(registry_mod.REGISTRY_DIR)])
        return {"FINISHED"}


class CLAUDE_PAIR_OT_edit_global_doc(Operator):
    bl_idname = "claude_pair.edit_global_doc"
    bl_label = "Edit Global Doc"
    bl_description = "Open the Vault's Blender + Claude workflow doc in your default markdown editor"
    bl_options = {"REGISTER"}

    def execute(self, context):
        del context
        if not VAULT_GLOBAL_DOC.exists():
            self.report(
                {"ERROR"},
                f"Vault doc not found at {VAULT_GLOBAL_DOC} (is the Vault mounted?).",
            )
            return {"CANCELLED"}
        subprocess.Popen(["open", str(VAULT_GLOBAL_DOC)])
        return {"FINISHED"}


class CLAUDE_PAIR_OT_edit_pointer_doc(Operator):
    bl_idname = "claude_pair.edit_pointer_doc"
    bl_label = "Edit Pointer Doc"
    bl_description = "Open ~/.claude-pair/global-context.md (the launcher's --append-system-prompt source)"
    bl_options = {"REGISTER"}

    def execute(self, context):
        del context
        if not GLOBAL_POINTER_DOC.exists():
            try:
                GLOBAL_POINTER_DOC.parent.mkdir(parents=True, exist_ok=True)
                GLOBAL_POINTER_DOC.write_text(GLOBAL_POINTER_TEMPLATE)
            except Exception as ex:  # pylint: disable=broad-exception-caught
                self.report({"ERROR"}, f"Could not create pointer doc: {ex}")
                return {"CANCELLED"}
        subprocess.Popen(["open", str(GLOBAL_POINTER_DOC)])
        return {"FINISHED"}


class CLAUDE_PAIR_OT_edit_project_md(Operator):
    bl_idname = "claude_pair.edit_project_md"
    bl_label = "Edit Project CLAUDE.md"
    bl_description = "Open CLAUDE.md in the current pair's cwd (or the blend file's dir)"
    bl_options = {"REGISTER"}

    def execute(self, context):
        del context
        cwd = _resolve_project_cwd()
        if cwd is None:
            self.report(
                {"ERROR"},
                "No active pair and the blend file is unsaved — nowhere to put CLAUDE.md.",
            )
            return {"CANCELLED"}
        target = cwd / "CLAUDE.md"
        if not target.exists():
            try:
                target.write_text(PROJECT_MD_TEMPLATE)
            except Exception as ex:  # pylint: disable=broad-exception-caught
                self.report({"ERROR"}, f"Could not create {target}: {ex}")
                return {"CANCELLED"}
        subprocess.Popen(["open", str(target)])
        return {"FINISHED"}


class CLAUDE_PAIR_OT_write_project_permissions(Operator):
    bl_idname = "claude_pair.write_project_permissions"
    bl_label = "Drop Permissions"
    bl_description = "Write .claude/settings.local.json into the project (only if absent)"
    bl_options = {"REGISTER"}

    def execute(self, context):
        del context
        cwd = _resolve_project_cwd()
        if cwd is None:
            self.report(
                {"ERROR"},
                "No active pair and the blend file is unsaved — nowhere to drop permissions.",
            )
            return {"CANCELLED"}
        try:
            wrote, msg = _write_project_permissions(cwd)
        except Exception as ex:  # pylint: disable=broad-exception-caught
            self.report({"ERROR"}, f"Failed: {ex}")
            return {"CANCELLED"}
        self.report({"INFO"}, msg)
        return {"FINISHED"}


# ─── UI Panel ───────────────────────────────────────────────────────────────────

class CLAUDE_PAIR_PT_panel(Panel):
    bl_idname = "CLAUDE_PAIR_PT_panel"
    bl_label = "Claude Pair"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Claude"

    def draw(self, context):
        del context
        layout = self.layout
        entry = _current_pair()
        stored_uuid = _stored_session_id()
        if entry is None:
            # No active pair. Show Pair Now + (if a stored UUID exists) Re-pair & Resume,
            # plus an escape hatch for starting fresh.
            col = layout.column(align=True)
            col.operator("claude_pair.pair_now", icon="LINKED")
            if stored_uuid:
                col.operator("claude_pair.repair_resume", icon="FILE_REFRESH")
                box = layout.box()
                box.label(text="Stored session for this .blend:", icon="LINKED")
                row = box.row()
                row.enabled = False
                row.label(text=stored_uuid)
                box.operator("claude_pair.new_session_for_file", icon="FILE_NEW")
            else:
                # No stored ID — still expose 'New session' as an alias of Pair Now,
                # so users can find the explicit "start fresh" button in either state.
                layout.operator("claude_pair.new_session_for_file", icon="FILE_NEW")
            layout.label(text=f"Blender pid: {_BLENDER_PID}")
        else:
            col = layout.column(align=True)
            col.label(text=entry.get("title", ""), icon="CHECKMARK")
            col.label(text=f"Port: {entry.get('port')}")
            bf = entry.get("blendfile") or "(unsaved)"
            col.label(text=f"File: {Path(bf).name if bf else '(unsaved)'}")
            row = layout.row(align=True)
            row.operator("claude_pair.reveal", icon="WINDOW")
            row.operator("claude_pair.unpair", icon="UNLINKED")
            layout.operator("claude_pair.agentic_layout", icon="MOD_ARRAY")

        layout.separator()
        box = layout.box()
        box.label(text="Docs", icon="TEXT")
        grid = box.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=True, align=True)
        grid.operator("claude_pair.edit_global_doc", icon="WORLD")
        grid.operator("claude_pair.edit_pointer_doc", icon="FILE_TEXT")
        grid.operator("claude_pair.edit_project_md", icon="FILE_BLEND")
        grid.operator("claude_pair.write_project_permissions", icon="LOCKED")

        layout.separator()
        box = layout.box()
        box.label(text="Shortcuts", icon="KEYINGSET")
        _draw_kmi_for(box, "claude_pair.reveal", "Reveal Terminal")
        _draw_kmi_for(box, "claude_pair.agentic_layout", "Agentic Layout")
        box.label(text="Rebind in Edit > Preferences > Keymap", icon="INFO")


# ─── Registration ───────────────────────────────────────────────────────────────

_classes = (
    CLAUDE_PAIR_OT_pair_now,
    CLAUDE_PAIR_OT_repair_resume,
    CLAUDE_PAIR_OT_new_session_for_file,
    CLAUDE_PAIR_OT_reveal,
    CLAUDE_PAIR_OT_agentic_layout,
    CLAUDE_PAIR_OT_unpair,
    CLAUDE_PAIR_OT_copy_diagnostics,
    CLAUDE_PAIR_OT_open_registry_dir,
    CLAUDE_PAIR_OT_edit_global_doc,
    CLAUDE_PAIR_OT_edit_pointer_doc,
    CLAUDE_PAIR_OT_edit_project_md,
    CLAUDE_PAIR_OT_write_project_permissions,
    CLAUDE_PAIR_PT_panel,
)


def _add_keymap():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if not kc:
        return
    km = kc.keymaps.new(name="Window", space_type="EMPTY")
    kmi = km.keymap_items.new("claude_pair.reveal", "C", "PRESS", ctrl=True, alt=True)
    _KEYMAPS.append((km, kmi))
    kmi = km.keymap_items.new(
        "claude_pair.agentic_layout", "C", "PRESS", ctrl=True, alt=True, shift=True,
    )
    _KEYMAPS.append((km, kmi))


def _remove_keymap():
    for km, kmi in _KEYMAPS:
        km.keymap_items.remove(kmi)
    _KEYMAPS.clear()


def _kmi_binding_label(operator_idname: str) -> str:
    """Return a human-readable summary of the current binding for an operator, or 'Unbound'.

    Reads from the addon keyconfig (the one Claude Pair owns), which is stable across
    reloads. The user keyconfig was attempted previously but rna_keymap_ui.draw_kmi
    against it can SIGSEGV on add-on disable/re-enable cycles.
    """
    try:
        wm = bpy.context.window_manager
        kc = wm.keyconfigs.addon
        if not kc:
            return "Unbound"
        km = kc.keymaps.get("Window")
        if not km:
            return "Unbound"
        for kmi in km.keymap_items:
            if kmi.idname != operator_idname:
                continue
            mods = []
            if kmi.ctrl: mods.append("Ctrl")
            if kmi.alt: mods.append("Alt")
            if kmi.shift: mods.append("Shift")
            if kmi.oskey: mods.append("Cmd")
            key = kmi.type if kmi.type != "NONE" else ""
            if not key:
                return "Unbound"
            return "+".join(mods + [key]) if mods else key
        return "Unbound"
    except Exception:  # pylint: disable=broad-exception-caught
        return "Unbound"


def _draw_kmi_for(layout, operator_idname: str, display_label: str):
    """Draw a single-line row showing the current binding for an operator.

    Read-only on purpose — drawing rna_keymap_ui.draw_kmi inside this panel crashed
    Blender during add-on reload (transient keymap dereference). Users can rebind via
    Edit > Preferences > Keymap, filtering for `claude_pair`.
    """
    binding = _kmi_binding_label(operator_idname)
    row = layout.row(align=True)
    row.label(text=f"{display_label}:")
    row.label(text=binding)


def _atexit_cleanup():
    """Best-effort cleanup when Blender exits."""
    try:
        registry_mod.remove(_BLENDER_PID)
    except Exception:  # pylint: disable=broad-exception-caught
        pass


@persistent
def _load_post_start_server(_dummy):
    """load_post handler: start the official MCP server after a .blend loads.

    Only runs when the user has opted in via the 'Start MCP server on Blender
    startup' preference. The server is started on a port from the configured
    range; the port is NOT pinned across loads (each launch is fresh). This
    handler does NOT auto-spawn a Claude session — the user still presses
    Re-pair & Resume to attach Claude.

    Why load_post and not register-time: register runs during add-on enable,
    which may happen before the user's startup .blend has loaded. load_post
    fires reliably after a file is open and bpy.context.scene is populated.
    """
    try:
        prefs = _prefs()
    except (KeyError, AttributeError):
        # Add-on not fully registered yet (e.g. mid-reload). Skip silently.
        return
    if not getattr(prefs, "start_server_on_load", False):
        return
    if pair_mod.is_official_mcp_running():
        if prefs.verbose_logging:
            print("[claude_pair] load_post: MCP server already running, skipping.")
        return
    try:
        port = pair_mod.find_free_port(
            start=prefs.port_range_start,
            end=prefs.port_range_end,
            host=prefs.mcp_host,
        )
        pair_mod.start_official_mcp_on_port(port, host=prefs.mcp_host)
        if prefs.verbose_logging:
            print(f"[claude_pair] load_post: started MCP server on port {port}.")
    except Exception as ex:  # pylint: disable=broad-exception-caught
        # Don't ever raise from a handler — Blender will keep emitting load_post
        # for every file open and we'd flood the console.
        print(f"[claude_pair] load_post: failed to start MCP server: {ex}")


def _register_load_post_handler():
    if _load_post_start_server not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_load_post_start_server)


def _unregister_load_post_handler():
    # Remove ALL refs (the @persistent decorator + reload paths can leave duplicates).
    handlers = bpy.app.handlers.load_post
    while _load_post_start_server in handlers:
        handlers.remove(_load_post_start_server)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    _add_keymap()
    _register_load_post_handler()
    atexit.register(_atexit_cleanup)


def unregister():
    _unregister_load_post_handler()
    _remove_keymap()
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
