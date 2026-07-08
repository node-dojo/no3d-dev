# SPDX-License-Identifier: GPL-3.0-or-later
"""The Save & Reload operator.

Flow:
  1. Validate: file has been saved at least once; save folder (if overridden) exists.
  2. Compute the next-available iteration path (stem.NNN.blend) by scanning the save folder.
  3. `bpy.ops.wm.save_as_mainfile(filepath=<next>, copy=False)` so the running session
     now points at the iteration file (the relaunch will reopen it).
  4. Discover the running Blender.app bundle from `bpy.app.binary_path`.
  5. Spawn the detached helper (helper.py) with --pid, --app, --blend.
  6. Call `bpy.ops.wm.quit_blender()`.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import bpy
from bpy.types import Operator

HOST_PACKAGE = __package__.rsplit(".", 1)[0]  # e.g. "no3d_asset_developer"


def _prefs():
    """Read the host add-on's preferences (Save & Reload props folded in)."""
    return bpy.context.preferences.addons[HOST_PACKAGE].preferences


# Matches "<stem>.<digits>.blend" — used to detect-and-strip an existing
# iteration suffix from the current file's name. Width 2–6 covers the
# `iteration_digits` pref range (default 3).
ITERATION_SUFFIX_RE = re.compile(r"^(?P<stem>.+?)\.(?P<num>\d{2,6})$")


# --------------------------------------------------------------------------- #
# Iteration save logic
# --------------------------------------------------------------------------- #

def _flatten_stem(blend_path: Path) -> str:
    """Return the stem of `blend_path` with any iteration suffix stripped.

    Example: Path('foo.005.blend').stem == 'foo.005' -> returns 'foo'.
             Path('foo.blend').stem == 'foo'         -> returns 'foo'.
    """
    stem = blend_path.stem  # filename minus '.blend'
    m = ITERATION_SUFFIX_RE.match(stem)
    if m:
        return m.group("stem")
    return stem


def _next_iteration_path(
    save_folder: Path,
    flat_stem: str,
    digits: int,
) -> Path:
    """Return Path for the next available `<flat_stem>.<NNN>.blend` in save_folder.

    Scans for ANY width of digits (2–6), so a folder with both `.01.blend` and
    `.001.blend` survivals still produces a unique next number. Padding of the
    NEW file is controlled by `digits`.
    """
    scan_re = re.compile(
        rf"^{re.escape(flat_stem)}\.(\d{{2,6}})\.blend$"
    )
    max_n = 0
    if save_folder.is_dir():
        for entry in save_folder.iterdir():
            if not entry.is_file():
                continue
            m = scan_re.match(entry.name)
            if not m:
                continue
            try:
                n = int(m.group(1))
            except ValueError:
                continue
            if n > max_n:
                max_n = n
    next_n = max_n + 1
    pad = max(digits, len(str(next_n)))  # never lose digits if we overflow
    return save_folder / f"{flat_stem}.{next_n:0{pad}d}.blend"


# --------------------------------------------------------------------------- #
# Blender app discovery
# --------------------------------------------------------------------------- #

def _resolve_app_bundle() -> Path | None:
    """Walk up from `bpy.app.binary_path` to find the .app bundle.

    Typical layout: /Applications/Blender 5.1.app/Contents/MacOS/Blender
    We want:        /Applications/Blender 5.1.app
    """
    binary = Path(bpy.app.binary_path)
    for ancestor in (binary, *binary.parents):
        if ancestor.suffix == ".app":
            return ancestor
    return None


# --------------------------------------------------------------------------- #
# Helper spawn
# --------------------------------------------------------------------------- #

def _helper_path() -> Path:
    """Path to the helper.py shipped with this add-on."""
    return Path(__file__).resolve().parent / "helper.py"


def _spawn_helper(pid: int, app_bundle: Path, blend_path: Path) -> tuple[bool, str]:
    """Spawn the detached relaunch helper. Returns (ok, message_for_user)."""
    helper = _helper_path()
    if not helper.is_file():
        return False, f"Helper script not found at {helper}"

    # Use the system python3, not Blender's embedded interpreter — the helper
    # must outlive Blender. macOS ships /usr/bin/python3 with the Command Line
    # Tools shim; falling back to plain "python3" lets PATH resolve it too.
    python_exe = "/usr/bin/python3"
    if not Path(python_exe).exists():
        python_exe = "python3"

    cmd = [
        python_exe,
        str(helper),
        "--pid", str(pid),
        "--app", str(app_bundle),
        "--blend", str(blend_path),
    ]

    try:
        # Detach: new session, no controlling tty, all stdio → /dev/null.
        # This is the macOS-correct way to launch a process that survives the
        # parent dying. os.fork() and shell '&' have edge cases here.
        devnull = subprocess.DEVNULL
        subprocess.Popen(
            cmd,
            stdin=devnull,
            stdout=devnull,
            stderr=devnull,
            start_new_session=True,
            close_fds=True,
        )
    except Exception as ex:  # noqa: BLE001
        return False, f"Could not spawn helper: {ex}"

    return True, " ".join(cmd)


# --------------------------------------------------------------------------- #
# Operator
# --------------------------------------------------------------------------- #

class SAVE_AND_RELOAD_OT_run(Operator):
    bl_idname = "save_and_reload.run"
    bl_label = "Save and Reload"
    bl_description = (
        "Save current file as the next iteration (.001, .002, ...), "
        "then quit and relaunch this Blender instance with the new file"
    )
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        del context
        # Allow the operator to be invoked even with an unsaved file so we can
        # produce a clean error in execute().
        return True

    def invoke(self, context, event):
        prefs = _prefs()
        if prefs.confirm_before_restart:
            return context.window_manager.invoke_confirm(self, event)
        return self.execute(context)

    def execute(self, context):
        del context
        prefs = _prefs()

        # 1. File-saved check
        current_filepath = bpy.data.filepath
        if not current_filepath:
            self.report(
                {"ERROR"},
                "Save the file once before using Save and Reload.",
            )
            return {"CANCELLED"}

        current = Path(current_filepath)
        if not current.is_file():
            self.report(
                {"ERROR"},
                f"Current .blend file is not on disk: {current}",
            )
            return {"CANCELLED"}

        # 2. Resolve save folder
        if prefs.save_folder:
            save_folder = Path(bpy.path.abspath(prefs.save_folder)).expanduser()
            if not save_folder.is_dir():
                self.report(
                    {"ERROR"},
                    f"Configured save folder does not exist: {save_folder}",
                )
                return {"CANCELLED"}
        else:
            save_folder = current.parent

        # 3. Compute next iteration
        flat_stem = _flatten_stem(current)
        next_path = _next_iteration_path(
            save_folder=save_folder,
            flat_stem=flat_stem,
            digits=int(prefs.iteration_digits),
        )

        # 4. Discover Blender.app bundle
        app_bundle = _resolve_app_bundle()
        if app_bundle is None:
            self.report(
                {"ERROR"},
                f"Could not find Blender.app bundle from {bpy.app.binary_path}",
            )
            return {"CANCELLED"}

        # 5. Save as new iteration (copy=False so this session re-points to it)
        try:
            bpy.ops.wm.save_as_mainfile(filepath=str(next_path), copy=False)
        except Exception as ex:  # noqa: BLE001
            self.report({"ERROR"}, f"Save failed: {ex}. Blender NOT relaunched.")
            return {"CANCELLED"}

        if not next_path.is_file():
            self.report(
                {"ERROR"},
                f"Save reported success but file is missing: {next_path}. "
                "Blender NOT relaunched.",
            )
            return {"CANCELLED"}

        # 6. Spawn detached relaunch helper
        my_pid = os.getpid()
        ok, msg = _spawn_helper(my_pid, app_bundle, next_path)
        if not ok:
            self.report(
                {"ERROR"},
                f"{msg}. Iteration saved at {next_path}, but Blender will not "
                "auto-relaunch — relaunch manually.",
            )
            return {"CANCELLED"}

        print(f"[save_and_reload] saved iteration: {next_path}")
        print(f"[save_and_reload] helper spawned: {msg}")
        print(f"[save_and_reload] quitting Blender (pid {my_pid}); "
              f"helper will reopen with {app_bundle}")

        # 7. Quit. Helper takes over from here.
        bpy.ops.wm.quit_blender()
        # Unreachable in practice, but keep the operator contract clean.
        return {"FINISHED"}


# --------------------------------------------------------------------------- #
# Menu integration
# --------------------------------------------------------------------------- #

def _menu_draw(self, context):
    del context
    self.layout.operator(
        SAVE_AND_RELOAD_OT_run.bl_idname,
        text="Save and Reload",
        icon="FILE_REFRESH",
    )


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

_classes = (SAVE_AND_RELOAD_OT_run,)
_KEYMAPS: list = []


def _add_keymap():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if not kc:
        return
    km = kc.keymaps.new(name="3D View", space_type="VIEW_3D")
    kmi = km.keymap_items.new(
        SAVE_AND_RELOAD_OT_run.bl_idname,
        type="R",
        value="PRESS",
        oskey=True,
        shift=True,
    )
    _KEYMAPS.append((km, kmi))


def _remove_keymap():
    for km, kmi in _KEYMAPS:
        try:
            km.keymap_items.remove(kmi)
        except Exception:  # noqa: BLE001
            pass
    _KEYMAPS.clear()


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    # File menu: append near Save As. TOPBAR_MT_file_save is the "Save / Save
    # As / ..." submenu in the File menu — appending here puts the entry in
    # the same neighborhood as Save As.
    bpy.types.TOPBAR_MT_file.append(_menu_draw)
    _add_keymap()


def unregister():
    _remove_keymap()
    try:
        bpy.types.TOPBAR_MT_file.remove(_menu_draw)
    except Exception:  # noqa: BLE001
        pass
    for cls in reversed(_classes):
        try:
            bpy.utils.unregister_class(cls)
        except (RuntimeError, ValueError):
            pass
