# SPDX-License-Identifier: GPL-3.0-or-later
"""Save a numbered iteration, quit Blender, and reopen the saved iteration."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import bpy
from bpy.types import Operator

ITERATION_SUFFIX_RE = re.compile(r"^(?P<stem>.+?)\.(?P<num>\d{2,6})$")
_KEYMAPS = []


def _prefs():
    return bpy.context.preferences.addons[__package__].preferences


def _flatten_stem(blend_path: Path) -> str:
    match = ITERATION_SUFFIX_RE.match(blend_path.stem)
    return match.group("stem") if match else blend_path.stem


def _next_iteration_path(save_folder: Path, flat_stem: str, digits: int) -> Path:
    pattern = re.compile(rf"^{re.escape(flat_stem)}\.(\d{{2,6}})\.blend$")
    found = []
    if save_folder.is_dir():
        for entry in save_folder.iterdir():
            match = pattern.match(entry.name) if entry.is_file() else None
            if match:
                found.append(int(match.group(1)))
    number = max(found, default=0) + 1
    width = max(digits, len(str(number)))
    return save_folder / f"{flat_stem}.{number:0{width}d}.blend"


def _resolve_app_bundle() -> Path | None:
    binary = Path(bpy.app.binary_path)
    return next((path for path in (binary, *binary.parents) if path.suffix == ".app"), None)


def _spawn_helper(pid: int, app_bundle: Path, blend_path: Path) -> tuple[bool, str]:
    helper = Path(__file__).resolve().parent / "helper.py"
    if not helper.is_file():
        return False, f"Helper script not found: {helper}"
    python_executable = "/usr/bin/python3" if Path("/usr/bin/python3").exists() else "python3"
    command = [
        python_executable,
        str(helper),
        "--pid", str(pid),
        "--app", str(app_bundle),
        "--blend", str(blend_path),
    ]
    try:
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except Exception as exc:
        return False, str(exc)
    return True, "helper started"


class NO3D_SR_OT_save_and_reload(Operator):
    bl_idname = "save_and_reload.run"
    bl_label = "Save and Reload"
    bl_description = "Save the next numbered iteration, then reopen it in this Blender version"
    bl_options = {"REGISTER"}

    def invoke(self, context, event):
        if _prefs().confirm_before_restart:
            return context.window_manager.invoke_confirm(self, event)
        return self.execute(context)

    def execute(self, _context):
        if not bpy.data.filepath:
            self.report({"ERROR"}, "Save the file once before using Save and Reload")
            return {"CANCELLED"}
        current = Path(bpy.data.filepath)
        if not current.is_file():
            self.report({"ERROR"}, f"Current Blender file is not on disk: {current}")
            return {"CANCELLED"}

        prefs = _prefs()
        save_folder = (
            Path(bpy.path.abspath(prefs.save_folder)).expanduser()
            if prefs.save_folder else current.parent
        )
        if not save_folder.is_dir():
            self.report({"ERROR"}, f"Save folder does not exist: {save_folder}")
            return {"CANCELLED"}
        app_bundle = _resolve_app_bundle()
        if app_bundle is None:
            self.report({"ERROR"}, "Could not resolve the running Blender.app bundle")
            return {"CANCELLED"}

        target = _next_iteration_path(save_folder, _flatten_stem(current), prefs.iteration_digits)
        try:
            bpy.ops.wm.save_as_mainfile(filepath=str(target), copy=False)
        except Exception as exc:
            self.report({"ERROR"}, f"Save failed: {exc}")
            return {"CANCELLED"}
        if not target.is_file():
            self.report({"ERROR"}, f"Save returned without creating {target}")
            return {"CANCELLED"}

        ok, message = _spawn_helper(os.getpid(), app_bundle, target)
        if not ok:
            self.report({"ERROR"}, f"Iteration saved, but relaunch failed: {message}")
            return {"CANCELLED"}
        bpy.ops.wm.quit_blender()
        return {"FINISHED"}


def _menu_draw(self, _context):
    self.layout.operator(NO3D_SR_OT_save_and_reload.bl_idname, icon="FILE_REFRESH")


def _add_keymap():
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig is None:
        return
    keymap = keyconfig.keymaps.new(name="3D View", space_type="VIEW_3D")
    item = keymap.keymap_items.new(
        NO3D_SR_OT_save_and_reload.bl_idname,
        type="R",
        value="PRESS",
        oskey=True,
        shift=True,
    )
    _KEYMAPS.append((keymap, item))


def register():
    bpy.utils.register_class(NO3D_SR_OT_save_and_reload)
    bpy.types.TOPBAR_MT_file.append(_menu_draw)
    _add_keymap()


def unregister():
    for keymap, item in _KEYMAPS:
        try:
            keymap.keymap_items.remove(item)
        except Exception:
            pass
    _KEYMAPS.clear()
    try:
        bpy.types.TOPBAR_MT_file.remove(_menu_draw)
    except Exception:
        pass
    bpy.utils.unregister_class(NO3D_SR_OT_save_and_reload)
