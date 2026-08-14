"""Blender controls for the canonical public NO3D product library."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess

import bpy
from bpy.app.handlers import persistent
from bpy.props import StringProperty
from bpy.types import Operator

from . import wip_sync

log = logging.getLogger(__name__)
PLAN_RE = re.compile(r"NO3D_PUBLISH_PLAN=([0-9a-f-]{36})", re.IGNORECASE)


def _prefs():
    addon = bpy.context.preferences.addons.get(__package__)
    return getattr(addon, "preferences", None) if addon else None


def _active_asset(context):
    candidate = getattr(context, "id", None)
    if candidate is not None and getattr(candidate, "asset_data", None):
        return candidate
    candidate = getattr(context, "active_object", None)
    if candidate is not None and getattr(candidate, "asset_data", None):
        return candidate
    for candidate in getattr(context, "selected_objects", ()):
        if getattr(candidate, "asset_data", None):
            return candidate
    return None


def _paths():
    prefs = _prefs()
    repo = bpy.path.abspath(getattr(prefs, "solvet_repo_path", "") or "")
    library = bpy.path.abspath(getattr(prefs, "public_library_path", "") or "")
    workflow = os.path.join(repo, "scripts", "product-workflow.js") if repo else ""
    return repo, library, workflow


def _linked_product(asset_name: str):
    _repo, library, _workflow = _paths()
    if not library or not os.path.isdir(library):
        return None
    for folder_name in os.listdir(library):
        folder = os.path.join(library, folder_name)
        if folder_name.startswith(".") or not os.path.isdir(folder):
            continue
        candidates = [os.path.join(folder, f"{folder_name}.json")]
        try:
            candidates.extend(
                os.path.join(folder, name) for name in os.listdir(folder)
                if name.endswith(".json") and not name.startswith(".")
            )
        except OSError:
            continue
        for path in dict.fromkeys(candidates):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, json.JSONDecodeError):
                continue
            if asset_name in (
                data.get("handle"), data.get("title"),
                (data.get("dashboard") or {}).get("blender_asset_name"),
            ):
                return data
    return None


def _run(args: list[str]) -> tuple[bool, str]:
    repo, library, workflow = _paths()
    if not repo or not os.path.isdir(repo):
        return False, "SOLVET repository is not configured"
    if not library or not os.path.isdir(library):
        return False, "Public product library is not configured"
    if not os.path.isfile(workflow):
        return False, f"Product workflow not found: {workflow}"
    doppler = shutil.which("doppler") or "/opt/homebrew/bin/doppler"
    node = shutil.which("node") or "/opt/homebrew/bin/node"
    if not os.path.isfile(doppler) or not os.path.isfile(node):
        return False, "Doppler or Node is not installed"
    command = [doppler, "run", "--", node, workflow, *args, "--library-root", library]
    result = subprocess.run(command, cwd=repo, text=True, capture_output=True, check=False)
    output = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
    if output:
        print(f"[NO3D Public Library]\n{output}")
    return result.returncode == 0, output


def _sync_current_to_wip(asset) -> tuple[bool, str, str]:
    wip = wip_sync.get_wip_folder()
    if not wip:
        return False, "WIP destination is empty; no files were changed", ""
    if not os.path.isdir(wip):
        return False, f"WIP destination does not exist: {wip}", ""
    ok, message = wip_sync.sync_one(asset, wip, _prefs())
    return ok, message, os.path.join(wip, asset.name)


def stage_linked_asset(asset, quiet: bool = False, export_first: bool = True) -> tuple[bool, str]:
    linked = _linked_product(asset.name)
    if not linked:
        return False, "Asset is not linked to a public product"
    if export_first:
        ok, message, source = _sync_current_to_wip(asset)
        if not ok:
            return False, message
    else:
        source = os.path.join(wip_sync.get_wip_folder(), asset.name)
        if not os.path.isdir(source):
            return False, "WIP stage source is unavailable"
    ok, output = _run(["stage", "--asset-name", asset.name, "--product", linked["handle"], "--source-folder", source])
    if ok:
        bpy.context.window_manager.no3d_public_status = f"Staged {asset.name} locally"
    elif not quiet:
        bpy.context.window_manager.no3d_public_status = "Public staging failed; see console"
    return ok, output or message


class NO3D_OT_promote_public_draft(Operator):
    bl_idname = "no3d.promote_public_draft"
    bl_label = "Promote to Public Draft"
    bl_description = "Create a linked local catalog draft from the active asset; does not publish"
    bl_options = {"REGISTER"}

    def execute(self, context):
        asset = _active_asset(context)
        if not asset:
            self.report({"ERROR"}, "Select a marked asset first")
            return {"CANCELLED"}
        ok, message, source = _sync_current_to_wip(asset)
        if not ok:
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        ok, output = _run(["promote", "--asset-name", asset.name, "--source-folder", source])
        if not ok:
            self.report({"ERROR"}, output[-240:] or "Promotion failed")
            return {"CANCELLED"}
        context.window_manager.no3d_public_status = f"Draft created for {asset.name}; nothing published"
        self.report({"INFO"}, f"Created public draft for {asset.name}")
        return {"FINISHED"}


class NO3D_OT_stage_public_update(Operator):
    bl_idname = "no3d.stage_public_update"
    bl_label = "Stage Current Asset"
    bl_description = "Export and stage this linked asset locally; does not publish"
    bl_options = {"REGISTER"}

    def execute(self, context):
        asset = _active_asset(context)
        if not asset:
            self.report({"ERROR"}, "Select a marked asset first")
            return {"CANCELLED"}
        ok, message = stage_linked_asset(asset)
        if not ok:
            self.report({"ERROR"}, message[-240:])
            return {"CANCELLED"}
        self.report({"INFO"}, f"Staged {asset.name}; nothing published")
        return {"FINISHED"}


class NO3D_OT_preview_public_update(Operator):
    bl_idname = "no3d.preview_public_update"
    bl_label = "Review & Publish Update"
    bl_description = "Run read-only remote checks and create a content-bound publish plan"
    bl_options = {"REGISTER"}

    def execute(self, context):
        asset = _active_asset(context)
        if not asset:
            self.report({"ERROR"}, "Select a marked asset first")
            return {"CANCELLED"}
        linked = _linked_product(asset.name)
        if not linked:
            self.report({"ERROR"}, "Promote this asset to a public draft first")
            return {"CANCELLED"}
        ok, output = _run(["preview", "--product", linked["handle"]])
        match = PLAN_RE.search(output)
        if not ok or not match:
            self.report({"ERROR"}, (output[-240:] if output else "Preview failed"))
            return {"CANCELLED"}
        context.window_manager.no3d_public_publish_plan = match.group(1)
        context.window_manager.no3d_public_status = f"Reviewed {asset.name}; plan ready for 30 minutes"
        self.report({"INFO"}, "Review passed. Use Publish Update to deploy this exact version.")
        return {"FINISHED"}


class NO3D_OT_activate_public_product(Operator):
    bl_idname = "no3d.activate_public_product"
    bl_label = "Mark Ready for Publication"
    bl_description = "Change the linked local catalog draft to active; still does not publish"
    bl_options = {"REGISTER"}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(
            self, event, title="Mark product ready?",
            message="This makes the next reviewed publish eligible for the website and member library.",
            confirm_text="Mark Ready",
        )

    def execute(self, context):
        asset = _active_asset(context)
        linked = _linked_product(asset.name) if asset else None
        if not linked:
            self.report({"ERROR"}, "No linked public draft selected")
            return {"CANCELLED"}
        ok, output = _run(["activate", "--product", linked["handle"]])
        if not ok:
            self.report({"ERROR"}, output[-240:] or "Could not activate product")
            return {"CANCELLED"}
        context.window_manager.no3d_public_status = f"{asset.name} is ready for reviewed publication"
        self.report({"INFO"}, "Product marked active locally; nothing published yet")
        return {"FINISHED"}


class NO3D_OT_publish_public_update(Operator):
    bl_idname = "no3d.publish_public_update"
    bl_label = "Publish Update"
    bl_description = "Publish the exact unchanged version represented by the reviewed plan"
    bl_options = {"REGISTER"}

    def invoke(self, context, _event):
        return context.window_manager.invoke_confirm(
            self, _event, title="Publish NO3D product update?",
            message="This uploads media/assets, updates the live catalog, and regenerates the member manifest.",
            confirm_text="Publish Update",
        )

    def execute(self, context):
        plan = context.window_manager.no3d_public_publish_plan
        if not plan:
            self.report({"ERROR"}, "Run Review & Publish Update first")
            return {"CANCELLED"}
        ok, output = _run(["publish", "--plan", plan])
        if not ok:
            context.window_manager.no3d_public_status = "Publish incomplete; see console and review again"
            self.report({"ERROR"}, output[-240:] or "Publish failed")
            return {"CANCELLED"}
        context.window_manager.no3d_public_publish_plan = ""
        context.window_manager.no3d_public_status = "Published and manifest regenerated"
        self.report({"INFO"}, "NO3D product update published")
        return {"FINISHED"}


@persistent
def _stage_linked_on_save(_dummy):
    prefs = _prefs()
    if prefs and not getattr(prefs, "public_auto_stage", True):
        return
    asset = _active_asset(bpy.context)
    if asset and _linked_product(asset.name):
        try:
            stage_linked_asset(asset, quiet=True, export_first=False)
        except Exception:
            log.exception("Could not auto-stage linked public asset")


_classes = (
    NO3D_OT_promote_public_draft,
    NO3D_OT_stage_public_update,
    NO3D_OT_activate_public_product,
    NO3D_OT_preview_public_update,
    NO3D_OT_publish_public_update,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.no3d_public_status = StringProperty(default="No public changes staged")
    bpy.types.WindowManager.no3d_public_publish_plan = StringProperty(default="")
    if _stage_linked_on_save not in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.append(_stage_linked_on_save)


def unregister():
    try:
        bpy.app.handlers.save_post.remove(_stage_linked_on_save)
    except ValueError:
        pass
    for name in ("no3d_public_publish_plan", "no3d_public_status"):
        try:
            delattr(bpy.types.WindowManager, name)
        except AttributeError:
            pass
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
