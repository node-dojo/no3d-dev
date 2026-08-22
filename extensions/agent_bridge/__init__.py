# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent Bridge — Blender-side serve+register so agents can target this
instance by its .blend filename via the Agent Bridge MCP server."""

__all__ = ("register", "unregister", "build_register_payload")

import os
import sys
import shlex
import shutil
import tempfile
import subprocess
from pathlib import Path


def build_register_payload(pid: int, port: int, host: str, blendfile: str) -> dict:
    stem = Path(blendfile).stem if blendfile else ""
    return {
        "blender_pid": pid,
        "port": port,
        "host": host,
        "blendfile": blendfile,
        "blendfile_stem": stem,
    }


# ---------------------------------------------------------------------------
# Instructions discovery (bpy-free so it's testable/importable outside Blender)
# ---------------------------------------------------------------------------

# Filenames we treat as "agent instruction" documents.
_INSTRUCTION_FILENAMES = ("CLAUDE.md", "AGENTS.md", "claude.md", "agents.md")

# Directory of THIS add-on. Used to surface the Agent Bridge tier's own docs.
_THIS_ADDON_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Anchor paths — single source of truth, environment-variable overridable.
# Every user-facing path claim in this add-on (primer, drift map, CLAUDE.md)
# resolves through here, so a folder rename or machine migration is a
# one-var edit rather than a doc-wide search-and-replace.
# ---------------------------------------------------------------------------

_ANCHOR_ENV_VARS = (
    # (env var, default relative to $HOME, human label)
    ("NO3D_PROJECTS_ROOT",       "Projects",                                                     "Add-on / code repos root"),
    ("NO3D_MONOREPO",            "Projects/no3d-asset-developer",                                "No3d Dev monorepo"),
    ("NO3D_BLEND_PROJECTS_ROOT", "Library/CloudStorage/Dropbox/Caveman Creative/"
                                  "THE WELL_Digital Assets/THE WELL_play files",                 "Blender .blend projects root"),
    ("VAULT_001",                "Vault_001",                                                    "Vault (ship log lives here)"),
    ("AGENT_BRIDGE_SRC",         "Projects/agent-bridge/agent_bridge",                           "Agent Bridge canonical source"),
)


def resolve_anchors() -> dict:
    """Return a dict of {env_var: {path, source, label, exists}} for every anchor.

    `source` is 'env' when the env var was set (even to an empty string that
    resolves), or 'default' when we fell back to $HOME/<default>.
    """
    home = Path.home()
    out = {}
    for var, default_rel, label in _ANCHOR_ENV_VARS:
        env_val = os.environ.get(var)
        if env_val:
            p = Path(env_val).expanduser()
            source = "env"
        else:
            p = home / default_rel
            source = "default"
        out[var] = {
            "path": str(p),
            "source": source,
            "label": label,
            "exists": p.exists(),
        }
    return out


def _first_existing(paths):
    for p in paths:
        if p.exists() and p.is_file():
            return p
    return None


# ---------------------------------------------------------------------------
# Add-on repo discovery (bpy-free — reads the filesystem, not Blender state).
# The rule: any directory (up to depth 4) under NO3D_PROJECTS_ROOT that
# contains a blender_manifest.toml is a Blender add-on repo. Its git remote
# and dirty flag come from the enclosing git repo. Vendor relationships
# come from the monorepo's vendor.toml.
# ---------------------------------------------------------------------------


def _git(repo: Path, *args) -> str:
    """Run `git -C <repo> <args>` and return stripped stdout, or '' on error."""
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def _find_git_root(start: Path) -> Path | None:
    """Walk up from `start` looking for a .git directory. Return the repo root or None."""
    cur = start
    for _ in range(8):
        if (cur / ".git").exists():
            return cur
        if cur.parent == cur:
            return None
        cur = cur.parent
    return None


def _read_vendor_toml(monorepo: Path) -> dict:
    """Return {ext_id: {source, ref, subdir}} from monorepo/vendor.toml. Empty on missing/parse-error."""
    vt = monorepo / "vendor.toml"
    if not vt.exists():
        return {}
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore
        except ImportError:
            return {}
    try:
        return tomllib.loads(vt.read_text())
    except Exception:  # pylint: disable=broad-exception-caught
        return {}


def discover_addon_repos(projects_root: Path,
                         monorepo: Path | None = None,
                         max_depth: int = 4) -> list[dict]:
    """Enumerate Blender add-on repos under `projects_root`.

    For each: {id, path, manifest_path, git_root, remote, branch, head, dirty,
              vendor_source (or None), monorepo (or None)}.
    """
    if not projects_root.exists():
        return []

    # Vendor relationships (if the monorepo is present).
    vendor_map: dict[str, dict] = {}
    if monorepo is not None and monorepo.exists():
        vendor_map = _read_vendor_toml(monorepo)

    results: list[dict] = []
    seen: set[str] = set()

    def walk(root: Path, depth: int):
        if depth > max_depth:
            return
        # Skip anything under an _archive/ tree.
        if any(part.startswith("_archive") for part in root.parts):
            return
        try:
            entries = list(root.iterdir())
        except (PermissionError, OSError):
            return
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name.startswith(".") or entry.name == "__pycache__":
                    continue
                walk(entry, depth + 1)
            elif entry.name == "blender_manifest.toml":
                addon_dir = entry.parent
                key = str(addon_dir.resolve())
                if key in seen:
                    continue
                seen.add(key)
                # Extract id from manifest (best-effort — cheap regex, no toml parse).
                addon_id = addon_dir.name
                try:
                    manifest_text = entry.read_text()
                    import re
                    m = re.search(r'^\s*id\s*=\s*"([^"]+)"', manifest_text, re.MULTILINE)
                    if m:
                        addon_id = m.group(1)
                    ver_m = re.search(r'^\s*version\s*=\s*"([^"]+)"', manifest_text, re.MULTILINE)
                    version = ver_m.group(1) if ver_m else ""
                except OSError:
                    version = ""
                git_root = _find_git_root(addon_dir)
                remote = _git(git_root, "remote", "get-url", "origin") if git_root else ""
                branch = _git(git_root, "symbolic-ref", "--short", "HEAD") if git_root else ""
                head = _git(git_root, "log", "-1", "--format=%h %cs %s") if git_root else ""
                dirty_out = _git(git_root, "status", "--porcelain") if git_root else ""
                dirty = bool(dirty_out)
                # Is this a vendored copy?
                vendor_source = None
                if git_root and vendor_map:
                    monorepo_resolved = monorepo.resolve() if monorepo else None
                    if monorepo_resolved and monorepo_resolved in addon_dir.resolve().parents:
                        vendor_source = vendor_map.get(addon_id)
                results.append({
                    "id": addon_id,
                    "version": version,
                    "path": str(addon_dir),
                    "manifest_path": str(entry),
                    "git_root": str(git_root) if git_root else None,
                    "remote": remote or None,
                    "branch": branch or None,
                    "head": head or None,
                    "dirty": dirty,
                    "vendor_source": vendor_source,
                })

    walk(projects_root, 0)
    return results


def discover_blend_projects(blend_root: Path, max_depth: int = 3) -> list[dict]:
    """Enumerate .blend files under `blend_root` (shallow). Returns
    [{name, path, size, mtime, parent}] sorted by mtime desc, capped at 200."""
    if not blend_root.exists():
        return []
    found: list[dict] = []

    def walk(root: Path, depth: int):
        if depth > max_depth or len(found) >= 200:
            return
        try:
            entries = list(root.iterdir())
        except (PermissionError, OSError):
            return
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir() and not entry.name.startswith("."):
                walk(entry, depth + 1)
            elif entry.is_file() and entry.suffix.lower() == ".blend":
                try:
                    stat = entry.stat()
                except OSError:
                    continue
                found.append({
                    "name": entry.name,
                    "path": str(entry),
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                    "parent": entry.parent.name,
                })

    walk(blend_root, 0)
    found.sort(key=lambda r: r["mtime"], reverse=True)
    return found


def discover_instruction_files(project_dir: Path | None) -> list[dict]:
    """Return a list of instruction-file records for the strict three-tier
    hierarchy: Global → Agent Bridge → Project.

    Each record: {'scope': 'global'|'agent_bridge'|'project', 'label': str, 'path': str}
    """
    home = Path.home()
    found: list[dict] = []

    # --- Global (user-level) ------------------------------------------------
    global_candidates = [
        home / ".claude" / "CLAUDE.md",
        home / ".config" / "claude" / "CLAUDE.md",
        home / "CLAUDE.md",
        home / ".claude" / "AGENTS.md",
        home / "AGENTS.md",
    ]
    for p in global_candidates:
        if p.exists() and p.is_file():
            found.append({"scope": "global", "label": str(p.relative_to(home)), "path": str(p)})

    # --- Agent Bridge (this add-on's own docs) -----------------------------
    # Only this add-on's directory — no walk of unrelated add-ons.
    for name in _INSTRUCTION_FILENAMES:
        candidate = _THIS_ADDON_DIR / name
        if candidate.exists() and candidate.is_file():
            found.append({
                "scope": "agent_bridge",
                "label": name,
                "path": str(candidate),
            })
            break  # first hit wins; CLAUDE.md preferred over AGENTS.md

    # --- Project (blend file directory + its .claude/) ---------------------
    if project_dir is not None:
        proj_candidates = [
            project_dir / "CLAUDE.md",
            project_dir / "AGENTS.md",
            project_dir / ".claude" / "CLAUDE.md",
            project_dir / ".claude" / "AGENTS.md",
        ]
        for p in proj_candidates:
            if p.exists() and p.is_file():
                try:
                    label = str(p.relative_to(project_dir))
                except ValueError:
                    label = p.name
                found.append({"scope": "project", "label": label, "path": str(p)})

    return found


# ---------------------------------------------------------------------------
# Terminal / Claude launcher (bpy-free helpers)
# ---------------------------------------------------------------------------

def _build_primer_prompt(project_dir: Path,
                        stem: str,
                        pid: int | None,
                        port: int | None,
                        instructions: list[dict],
                        anchors: dict | None = None,
                        asset_libraries: list[dict] | None = None) -> str:
    """Build a concise system-prompt primer for `claude --append-system-prompt`.

    Anchors + asset libs give Claude a durable frame of reference: instead of
    hardcoding paths, we hand over the env-var-anchored map so a folder
    rename doesn't invalidate the primer.
    """
    lines = []
    lines.append(
        f"You are launched from the Blender project '{stem or '(unsaved)'}' at "
        f"{project_dir}. Prioritize being useful for Blender + add-on work in this project."
    )
    if pid is not None and port is not None:
        lines.append(
            f"This Blender instance is registered with Agent Bridge as pid={pid} on port {port}. "
            f"Route bpy calls through the agent-bridge MCP server targeting stem '{stem}'."
        )
    if instructions:
        lines.append("Read these instruction docs first (globals → agent bridge → project):")
        for row in instructions:
            lines.append(f"  - [{row['scope']}] {row['path']}")
    if anchors:
        lines.append("Anchor paths (env-var overridable; use these, don't hardcode):")
        for var, info in anchors.items():
            mark = "" if info["exists"] else "  [missing]"
            lines.append(f"  - ${var} = {info['path']}{mark}  # {info['label']}")
        lines.append(
            "To enumerate current add-on repos, walk $NO3D_PROJECTS_ROOT for blender_manifest.toml. "
            "To identify vendored extensions, read $NO3D_MONOREPO/vendor.toml. "
            "For related .blend projects, look under $NO3D_BLEND_PROJECTS_ROOT."
        )
    if asset_libraries:
        lines.append("Blender asset libraries currently registered in this instance:")
        for lib in asset_libraries:
            lines.append(f"  - {lib['name']}: {lib['path']}")
    lines.append(
        "When you finish reading, state which docs you loaded and summarize the rules that apply."
    )
    return "\n".join(lines)


def _write_launch_command_file(project_dir: Path, primer: str) -> Path:
    """Write a temporary .command file that cd's to the project and runs `claude`.

    Using a .command file avoids AppleScript quoting hell and works whether the
    user has `claude` on PATH or aliased in their shell rc (interactive login shell).
    """
    tmpdir = Path(tempfile.gettempdir())
    script = tmpdir / f"agent_bridge_claude_{os.getpid()}.command"
    # `exec $SHELL -ilc` ensures the user's PATH/aliases from .zshrc/.bashrc are loaded.
    quoted_dir = shlex.quote(str(project_dir))
    quoted_primer = shlex.quote(primer)
    body = (
        "#!/bin/bash\n"
        f"cd {quoted_dir} || exit 1\n"
        "echo '── Agent Bridge: launching Claude Code with primed context ──'\n"
        "echo\n"
        f"exec \"$SHELL\" -ilc 'claude --append-system-prompt {quoted_primer}'\n"
    )
    script.write_text(body)
    script.chmod(0o755)
    return script


# --- Blender-only below (guarded so the module imports without bpy for tests) ---
try:
    import bpy
    from bpy.types import Operator, Panel
    from bpy.props import StringProperty
    _HAS_BPY = True
except ImportError:
    _HAS_BPY = False

if _HAS_BPY:
    from . import registry as reg
    from . import serve_helpers as sh

    _PID = os.getpid()

    # Session-scoped opt-out. Set True when the user clicks *Stop Serving* so
    # subsequent load_post / save_post events (or a re-triggered auto-serve
    # timer) don't quietly resurrect the server against the user's intent.
    # Cleared when they click *Serve to Agents* again. Resets on Blender
    # restart (module reload).
    _user_stopped = False

    _AUTO_SERVE_DELAY = 0.5  # seconds after register before first auto-serve

    def _asset_libraries() -> list[dict]:
        """Enumerate the asset libraries configured in this Blender instance."""
        out = []
        try:
            libs = bpy.context.preferences.filepaths.asset_libraries
        except (AttributeError, RuntimeError):
            return out
        for lib in libs:
            out.append({
                "name": getattr(lib, "name", "(unnamed)"),
                "path": getattr(lib, "path", ""),
            })
        return out

    # -----------------------------------------------------------------------
    # Existing serve / stop operators
    # -----------------------------------------------------------------------

    class AGENT_BRIDGE_OT_serve(Operator):
        bl_idname = "agent_bridge.serve"
        bl_label = "Serve to Agents"
        bl_description = "Start this Blender's MCP server and register it so agents can target it by .blend name"
        bl_options = {"REGISTER"}

        def execute(self, context):
            del context
            global _user_stopped
            prefs_host = "localhost"
            try:
                if not sh.is_official_mcp_running():
                    port = sh.find_free_port(host=prefs_host)
                    sh.start_official_mcp_on_port(port, host=prefs_host)
                else:
                    port = sh.official_mcp_prefs().port
            except Exception as ex:  # pylint: disable=broad-exception-caught
                self.report({"ERROR"}, f"Could not start MCP server: {ex}")
                return {"CANCELLED"}
            blendfile = bpy.data.filepath or ""
            reg.write(_PID, build_register_payload(_PID, port, prefs_host, blendfile))
            # Explicit user action to serve → re-arm auto-serve for future events.
            _user_stopped = False
            self.report({"INFO"}, f"Serving '{Path(blendfile).stem or '(unsaved)'}' on :{port}")
            return {"FINISHED"}

    class AGENT_BRIDGE_OT_stop(Operator):
        bl_idname = "agent_bridge.stop"
        bl_label = "Stop Serving"
        bl_description = "Stop this Blender's MCP server and remove it from the agent registry"
        bl_options = {"REGISTER"}

        def execute(self, context):
            del context
            global _user_stopped
            try:
                sh.stop_official_mcp()
            except Exception:  # pylint: disable=broad-exception-caught
                pass
            reg.remove(_PID)
            # Respect the user's stop intent for the rest of the session — do
            # not let a subsequent .blend load quietly restart the server.
            _user_stopped = True
            self.report({"INFO"}, "Stopped serving. (Auto-serve disabled until you click Serve or restart Blender.)")
            return {"FINISHED"}

    # -----------------------------------------------------------------------
    # NEW: clipboard-copy for live-instance rows
    # -----------------------------------------------------------------------

    class AGENT_BRIDGE_OT_copy_instance(Operator):
        bl_idname = "agent_bridge.copy_instance"
        bl_label = "Copy Instance Line"
        bl_description = "Copy this instance's identifier line to the clipboard"
        bl_options = {"REGISTER", "INTERNAL"}

        payload: StringProperty(default="")  # type: ignore[valid-type]

        def execute(self, context):
            if not self.payload:
                self.report({"WARNING"}, "Nothing to copy.")
                return {"CANCELLED"}
            context.window_manager.clipboard = self.payload
            # Also emit a short user-facing hint in the info bar.
            short = self.payload if len(self.payload) < 60 else self.payload[:57] + "…"
            self.report({"INFO"}, f"Copied: {short}")
            return {"FINISHED"}

    # -----------------------------------------------------------------------
    # NEW: Launch a Claude Code terminal primed for this project
    # -----------------------------------------------------------------------

    class AGENT_BRIDGE_OT_launch_claude(Operator):
        bl_idname = "agent_bridge.launch_claude"
        bl_label = "Launch Claude Terminal Here"
        bl_description = (
            "Open a Terminal at this .blend's project directory and start Claude Code with a "
            "primed system prompt (global rules + add-on docs + local CLAUDE.md)."
        )
        bl_options = {"REGISTER"}

        def execute(self, context):
            del context
            blendfile = bpy.data.filepath or ""
            if blendfile:
                project_dir = Path(blendfile).parent
                stem = Path(blendfile).stem
            else:
                project_dir = Path.home()
                stem = ""
            entry = reg.read(_PID)
            port = entry.get("port") if entry else None
            instructions = discover_instruction_files(project_dir)
            anchors = resolve_anchors()
            asset_libs = _asset_libraries()
            primer = _build_primer_prompt(
                project_dir, stem, _PID, port, instructions,
                anchors=anchors, asset_libraries=asset_libs,
            )

            if sys.platform == "darwin":
                try:
                    script = _write_launch_command_file(project_dir, primer)
                    subprocess.Popen(["open", "-a", "Terminal", str(script)])
                    self.report(
                        {"INFO"},
                        f"Launched Claude in Terminal at {project_dir} ({len(instructions)} doc(s) referenced)."
                    )
                    return {"FINISHED"}
                except Exception as ex:  # pylint: disable=broad-exception-caught
                    self.report({"ERROR"}, f"Failed to launch Terminal: {ex}")
                    return {"CANCELLED"}

            # Non-mac fallback: dump the primer to a file and open its folder.
            try:
                script = _write_launch_command_file(project_dir, primer)
                self.report(
                    {"WARNING"},
                    f"Terminal auto-launch is macOS-only. A launch script was written to {script}."
                )
                # Best-effort: try common Linux terminals.
                for term in ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm"):
                    if shutil.which(term):
                        subprocess.Popen([term, "-e", "bash", str(script)])
                        break
                return {"FINISHED"}
            except Exception as ex:  # pylint: disable=broad-exception-caught
                self.report({"ERROR"}, f"Could not prepare launch script: {ex}")
                return {"CANCELLED"}

    # -----------------------------------------------------------------------
    # NEW: Refresh drift map — one-click ecosystem snapshot
    # -----------------------------------------------------------------------

    def _format_drift_report(anchors: dict,
                             addons: list[dict],
                             blend_projects: list[dict],
                             asset_libs: list[dict]) -> str:
        """Produce a markdown drift-check report Claude can read verbatim."""
        import datetime
        lines = ["# Agent Bridge — drift map", ""]
        try:
            lines.append(f"_Generated: {datetime.datetime.now().isoformat(timespec='seconds')}_")
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        lines.append("")

        # --- Anchors ---
        lines.append("## Anchor paths (env-var overridable)")
        lines.append("")
        for var, info in anchors.items():
            status = "OK" if info["exists"] else "MISSING"
            src = f"env={info['source']}"
            lines.append(f"- **${var}** ({status}, {src}) — `{info['path']}`  \n  _{info['label']}_")
        lines.append("")

        # --- Add-ons ---
        lines.append(f"## Add-on repos ({len(addons)} found)")
        lines.append("")
        if not addons:
            lines.append("_No blender_manifest.toml files found under $NO3D_PROJECTS_ROOT._")
        else:
            authored = [a for a in addons if a["vendor_source"] is None]
            vendored = [a for a in addons if a["vendor_source"] is not None]
            if authored:
                lines.append("### Authored-in-place")
                lines.append("")
                for a in authored:
                    dirty_mark = " **[DIRTY]**" if a["dirty"] else ""
                    lines.append(f"- **{a['id']}** v{a['version'] or '?'}{dirty_mark}")
                    lines.append(f"  - path: `{a['path']}`")
                    if a["remote"]:
                        lines.append(f"  - remote: `{a['remote']}` @ `{a['branch'] or '?'}`")
                    else:
                        lines.append("  - remote: _(none — local only)_")
                    if a["head"]:
                        lines.append(f"  - head: `{a['head']}`")
                lines.append("")
            if vendored:
                lines.append("### Vendored (canonical source lives elsewhere — DO NOT edit in place)")
                lines.append("")
                for a in vendored:
                    vs = a["vendor_source"] or {}
                    lines.append(f"- **{a['id']}** v{a['version'] or '?'}")
                    lines.append(f"  - vendored copy: `{a['path']}`")
                    lines.append(f"  - canonical: `{vs.get('source', '?')}` @ `{vs.get('ref', '?')}` "
                                 f"(subdir `{vs.get('subdir', '?')}`)")
                lines.append("")

        # --- Blend projects ---
        lines.append(f"## Recent .blend projects ({len(blend_projects)} found, top 20 by mtime)")
        lines.append("")
        if not blend_projects:
            lines.append("_No .blend files found under $NO3D_BLEND_PROJECTS_ROOT._")
        else:
            for b in blend_projects[:20]:
                lines.append(f"- `{b['name']}` — in `{b['parent']}/`  \n  `{b['path']}`")
        lines.append("")

        # --- Asset libraries ---
        lines.append(f"## Asset libraries registered in this Blender ({len(asset_libs)})")
        lines.append("")
        if not asset_libs:
            lines.append("_None configured in Preferences → File Paths → Asset Libraries._")
        else:
            for lib in asset_libs:
                lines.append(f"- **{lib['name']}** — `{lib['path']}`")
        lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("Regenerate via the N-panel's *Refresh Drift Map* button, or by calling "
                     "`bpy.ops.agent_bridge.refresh_drift_map()`.")
        return "\n".join(lines)

    class AGENT_BRIDGE_OT_refresh_drift_map(Operator):
        bl_idname = "agent_bridge.refresh_drift_map"
        bl_label = "Refresh Drift Map"
        bl_description = (
            "Scan add-on repos, .blend projects, asset libraries, and vendor.toml. "
            "Produce a timestamped drift report as a Blender Text datablock and copy to clipboard."
        )
        bl_options = {"REGISTER"}

        def execute(self, context):
            anchors = resolve_anchors()
            projects_root = Path(anchors["NO3D_PROJECTS_ROOT"]["path"])
            monorepo = Path(anchors["NO3D_MONOREPO"]["path"])
            blend_root = Path(anchors["NO3D_BLEND_PROJECTS_ROOT"]["path"])
            addons = discover_addon_repos(projects_root, monorepo)
            blend_projects = discover_blend_projects(blend_root)
            asset_libs = _asset_libraries()
            report = _format_drift_report(anchors, addons, blend_projects, asset_libs)

            # Replace/create a Text datablock named "agent-bridge:drift-map".
            name = "agent-bridge:drift-map"
            existing = bpy.data.texts.get(name)
            if existing:
                existing.clear()
                existing.write(report)
                text_db = existing
            else:
                text_db = bpy.data.texts.new(name)
                text_db.write(report)

            # Target any open Text Editor at it.
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == "TEXT_EDITOR":
                        for space in area.spaces:
                            if space.type == "TEXT_EDITOR":
                                space.text = text_db

            # Also copy the report to clipboard so it can be pasted anywhere.
            context.window_manager.clipboard = report

            dirty_count = sum(1 for a in addons if a["dirty"])
            self.report(
                {"INFO"},
                f"Drift map refreshed: {len(addons)} add-on(s) "
                f"({dirty_count} dirty), {len(blend_projects)} blend(s), "
                f"{len(asset_libs)} asset lib(s). Report → Text '{name}' + clipboard."
            )
            return {"FINISHED"}

    # -----------------------------------------------------------------------
    # NEW: Instruction-file open helpers
    # -----------------------------------------------------------------------

    def _load_into_blender_text_editor(filepath: str) -> str:
        """Load an external text file into Blender and, if possible, show it in
        an existing Text Editor area. Returns the Text datablock name."""
        # If already loaded (by filepath), reuse.
        existing = None
        try:
            for t in bpy.data.texts:
                if t.filepath and Path(t.filepath).resolve() == Path(filepath).resolve():
                    existing = t
                    break
        except OSError:
            existing = None
        text_db = existing or bpy.data.texts.load(filepath, internal=False)

        # Try to point an already-open text editor at it.
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "TEXT_EDITOR":
                    for space in area.spaces:
                        if space.type == "TEXT_EDITOR":
                            space.text = text_db
                    return text_db.name
        return text_db.name

    class AGENT_BRIDGE_OT_open_in_blender_text(Operator):
        bl_idname = "agent_bridge.open_in_blender_text"
        bl_label = "Open in Blender Text Editor"
        bl_description = "Load this file into a Blender Text datablock (and target any open Text Editor at it)"
        bl_options = {"REGISTER", "INTERNAL"}

        filepath: StringProperty(subtype="FILE_PATH", default="")  # type: ignore[valid-type]

        def execute(self, context):
            del context
            if not self.filepath or not Path(self.filepath).exists():
                self.report({"ERROR"}, "File not found.")
                return {"CANCELLED"}
            try:
                name = _load_into_blender_text_editor(self.filepath)
            except Exception as ex:  # pylint: disable=broad-exception-caught
                self.report({"ERROR"}, f"Load failed: {ex}")
                return {"CANCELLED"}
            self.report({"INFO"}, f"Loaded '{name}' — open a Text Editor area to view it.")
            return {"FINISHED"}

    class AGENT_BRIDGE_OT_open_in_default_editor(Operator):
        bl_idname = "agent_bridge.open_in_default_editor"
        bl_label = "Open in Default Markdown Editor"
        bl_description = "Open this file in the system's default application for its extension"
        bl_options = {"REGISTER", "INTERNAL"}

        filepath: StringProperty(subtype="FILE_PATH", default="")  # type: ignore[valid-type]

        def execute(self, context):
            del context
            if not self.filepath or not Path(self.filepath).exists():
                self.report({"ERROR"}, "File not found.")
                return {"CANCELLED"}
            try:
                if sys.platform == "darwin":
                    subprocess.Popen(["open", self.filepath])
                elif sys.platform == "win32":
                    os.startfile(self.filepath)  # type: ignore[attr-defined]
                else:
                    subprocess.Popen(["xdg-open", self.filepath])
            except Exception as ex:  # pylint: disable=broad-exception-caught
                self.report({"ERROR"}, f"Open failed: {ex}")
                return {"CANCELLED"}
            self.report({"INFO"}, f"Opened {Path(self.filepath).name} in default app.")
            return {"FINISHED"}

    class AGENT_BRIDGE_OT_reveal_folder(Operator):
        bl_idname = "agent_bridge.reveal_folder"
        bl_label = "Reveal Enclosing Folder"
        bl_description = "Open the folder that contains this file in the system file browser"
        bl_options = {"REGISTER", "INTERNAL"}

        filepath: StringProperty(subtype="FILE_PATH", default="")  # type: ignore[valid-type]

        def execute(self, context):
            del context
            p = Path(self.filepath) if self.filepath else None
            if not p or not p.exists():
                self.report({"ERROR"}, "Path not found.")
                return {"CANCELLED"}
            try:
                if sys.platform == "darwin":
                    # -R reveals the file in Finder rather than opening the folder generically.
                    subprocess.Popen(["open", "-R", str(p)])
                elif sys.platform == "win32":
                    subprocess.Popen(["explorer", "/select,", str(p)])
                else:
                    subprocess.Popen(["xdg-open", str(p.parent)])
            except Exception as ex:  # pylint: disable=broad-exception-caught
                self.report({"ERROR"}, f"Reveal failed: {ex}")
                return {"CANCELLED"}
            self.report({"INFO"}, f"Revealed {p.name}.")
            return {"FINISHED"}

    # -----------------------------------------------------------------------
    # Panel
    # -----------------------------------------------------------------------

    _SCOPE_ICON = {"global": "WORLD", "agent_bridge": "PLUGIN", "project": "FILE_BLEND"}
    _SCOPE_LABEL = {"global": "Global", "agent_bridge": "Agent Bridge", "project": "Project"}
    _SCOPE_ORDER = ("global", "agent_bridge", "project")

    class AGENT_BRIDGE_PT_panel(Panel):
        bl_idname = "AGENT_BRIDGE_PT_panel"
        bl_label = "Agent Bridge"
        bl_space_type = "VIEW_3D"
        bl_region_type = "UI"
        bl_category = "Agent"

        def draw(self, context):
            del context
            layout = self.layout
            entry = reg.read(_PID)

            # --- Serve / stop -------------------------------------------------
            if entry:
                row = layout.row(align=True)
                row.label(text=f"Serving :{entry.get('port')}", icon="CHECKMARK")
                row.operator("agent_bridge.stop", text="", icon="UNLINKED")
                layout.label(text=f"As: {entry.get('blendfile_stem') or '(unsaved)'}")
            else:
                layout.operator("agent_bridge.serve", icon="LINKED")
                if _user_stopped:
                    layout.label(text="Auto-serve paused for this session.", icon="INFO")

            # --- Live instances (click a row to copy it) ---------------------
            layout.separator()
            box = layout.box()
            box.label(text="Live instances (click to copy):", icon="OUTLINER")
            instances = reg.live_instances()
            if not instances:
                box.label(text="(none registered)", icon="DOT")
            else:
                current = [i for i in instances if i.get("blender_pid") == _PID]
                others = [i for i in instances if i.get("blender_pid") != _PID]

                def draw_instance_row(parent, instance):
                    """Draw one copyable registry entry in the given layout."""
                    i = instance
                    stem = reg.stem_of(i) or "(unsaved)"
                    port = i.get("port")
                    pid = i.get("blender_pid")
                    line = f"{stem}  :{port}  pid{pid}"
                    row = parent.row(align=True)
                    op = row.operator(
                        "agent_bridge.copy_instance",
                        text=line,
                        icon="COPYDOWN",
                        emboss=True,
                    )
                    op.payload = line

                # Keep the Blender hosting this panel visually distinct at the
                # top; the remaining live instances continue as the shared list.
                if current:
                    current_box = box.box()
                    draw_instance_row(current_box, current[0])
                    if others:
                        box.separator(factor=0.5)
                for instance in others:
                    draw_instance_row(box, instance)

            # --- Launch Claude Code terminal ---------------------------------
            layout.separator()
            launch_box = layout.box()
            launch_box.label(text="Claude Code", icon="CONSOLE")
            blendfile = bpy.data.filepath or ""
            proj_row = launch_box.row()
            proj_row.enabled = bool(blendfile)
            proj_row.operator(
                "agent_bridge.launch_claude",
                text="Launch Terminal Here",
                icon="PLAY",
            )
            if not blendfile:
                launch_box.label(text="Save the .blend first.", icon="INFO")
            else:
                launch_box.label(
                    text=f"@ {Path(blendfile).parent.name}/",
                    icon="FILE_FOLDER",
                )
            # Drift-check ritual made one click.
            launch_box.operator(
                "agent_bridge.refresh_drift_map",
                text="Refresh Drift Map",
                icon="FILE_REFRESH",
            )

            # --- Instruction docs --------------------------------------------
            layout.separator()
            instr_box = layout.box()
            instr_box.label(text="Instructions (system prompts):", icon="TEXT")
            project_dir = Path(blendfile).parent if blendfile else None
            docs = discover_instruction_files(project_dir)
            if not docs:
                instr_box.label(text="No CLAUDE.md / AGENTS.md found.", icon="DOT")
                instr_box.label(text="Drop one in the .blend's folder.", icon="INFO")
            else:
                # Group by scope in a stable order (Global → Agent Bridge → Project).
                for scope in _SCOPE_ORDER:
                    scope_docs = [d for d in docs if d["scope"] == scope]
                    if not scope_docs:
                        continue
                    header = instr_box.row()
                    header.label(
                        text=_SCOPE_LABEL[scope],
                        icon=_SCOPE_ICON[scope],
                    )
                    for d in scope_docs:
                        col = instr_box.column(align=True)
                        col.label(text=d["label"], icon="DOT")
                        btn_row = col.row(align=True)
                        op1 = btn_row.operator(
                            "agent_bridge.open_in_blender_text",
                            text="Blender",
                            icon="WORDWRAP_ON",
                        )
                        op1.filepath = d["path"]
                        op2 = btn_row.operator(
                            "agent_bridge.open_in_default_editor",
                            text="Editor",
                            icon="GREASEPENCIL",
                        )
                        op2.filepath = d["path"]
                        op3 = btn_row.operator(
                            "agent_bridge.reveal_folder",
                            text="Folder",
                            icon="FILE_FOLDER",
                        )
                        op3.filepath = d["path"]

    _classes = (
        AGENT_BRIDGE_OT_serve,
        AGENT_BRIDGE_OT_stop,
        AGENT_BRIDGE_OT_copy_instance,
        AGENT_BRIDGE_OT_launch_claude,
        AGENT_BRIDGE_OT_refresh_drift_map,
        AGENT_BRIDGE_OT_open_in_blender_text,
        AGENT_BRIDGE_OT_open_in_default_editor,
        AGENT_BRIDGE_OT_reveal_folder,
        AGENT_BRIDGE_PT_panel,
    )

    # -----------------------------------------------------------------------
    # Auto-serve: start the server on add-on register, re-register on file
    # load / save-as. Deferred via bpy.app.timers because register-time
    # bpy.context is restricted (running operators there is unreliable).
    # -----------------------------------------------------------------------

    def _auto_serve() -> None:
        """Invoke the serve operator if it's safe/desired to do so.

        Skips when: headless Blender, the user has stopped this session, or
        we're already serving (the operator is idempotent, but avoiding the
        extra Info-bar toast keeps things quiet on load_post/save_post).
        """
        if bpy.app.background:
            return
        if _user_stopped:
            return
        # Already registered → the operator would just rewrite the registry
        # entry. Do that anyway on file-load / save-as so the stem stays
        # current; only skip if the current blendfile matches the entry.
        entry = reg.read(_PID)
        current_blend = bpy.data.filepath or ""
        if (
            entry
            and entry.get("blendfile", "") == current_blend
            and sh.is_official_mcp_running()
        ):
            return
        try:
            bpy.ops.agent_bridge.serve()
        except (RuntimeError, AttributeError):
            # Operator context may not yet be ready on very early boot;
            # a follow-up load_post will retry.
            pass

    def _auto_serve_timer():
        _auto_serve()
        return None  # fire once

    @bpy.app.handlers.persistent
    def _agent_bridge_on_load(*_args):
        _auto_serve()

    @bpy.app.handlers.persistent
    def _agent_bridge_on_save(*_args):
        # Save-As changes bpy.data.filepath → registry stem needs to follow.
        _auto_serve()

    def _install_handlers() -> None:
        # Remove any stale copies from a prior module load (name-based match
        # so we survive addon disable/enable + reload cycles).
        for lst, name in (
            (bpy.app.handlers.load_post, "_agent_bridge_on_load"),
            (bpy.app.handlers.save_post, "_agent_bridge_on_save"),
        ):
            for h in list(lst):
                if getattr(h, "__name__", "") == name:
                    lst.remove(h)
        bpy.app.handlers.load_post.append(_agent_bridge_on_load)
        bpy.app.handlers.save_post.append(_agent_bridge_on_save)

    def _remove_handlers() -> None:
        for lst, name in (
            (bpy.app.handlers.load_post, "_agent_bridge_on_load"),
            (bpy.app.handlers.save_post, "_agent_bridge_on_save"),
        ):
            for h in list(lst):
                if getattr(h, "__name__", "") == name:
                    lst.remove(h)

    def register():
        global _user_stopped
        _user_stopped = False
        for cls in _classes:
            bpy.utils.register_class(cls)
        _install_handlers()
        # Defer the initial serve past the restricted register-time context.
        if not bpy.app.background:
            try:
                if not bpy.app.timers.is_registered(_auto_serve_timer):
                    bpy.app.timers.register(_auto_serve_timer, first_interval=_AUTO_SERVE_DELAY)
            except Exception:  # pylint: disable=broad-exception-caught
                pass

    def unregister():
        _remove_handlers()
        try:
            if bpy.app.timers.is_registered(_auto_serve_timer):
                bpy.app.timers.unregister(_auto_serve_timer)
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        # Best-effort stop so a disable doesn't leave a dangling server that
        # the user can't reach from the N-panel anymore.
        try:
            sh.stop_official_mcp()
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        reg.remove(_PID)
        for cls in reversed(_classes):
            bpy.utils.unregister_class(cls)
else:
    def register():
        raise RuntimeError("agent_bridge Blender side requires bpy")

    def unregister():
        pass
