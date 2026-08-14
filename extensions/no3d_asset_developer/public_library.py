"""Blender controls for the canonical public NO3D product library."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from datetime import date

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, CollectionProperty, IntProperty, StringProperty
from bpy.types import Operator, PropertyGroup, UIList

from . import wip_sync

log = logging.getLogger(__name__)
PLAN_RE = re.compile(r"NO3D_PUBLISH_PLAN=([0-9a-f-]{36})", re.IGNORECASE)
_public_recent_cache: tuple[float, str, list[tuple[str, str, float]]] = (0.0, "", [])


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
                return {**data, "_json_path": path, "_folder_path": folder}
    return None


def library_name() -> str:
    return getattr(_prefs(), "public_library_name", "NO3D Tools") or "NO3D Tools"


def list_recent_public_updates() -> list[tuple[str, str, float]]:
    _repo, library, _workflow = _paths()
    if not library or not os.path.isdir(library):
        return []
    global _public_recent_cache
    cached_at, cached_library, cached_updates = _public_recent_cache
    if cached_library == library and time.monotonic() - cached_at < 2.0:
        return cached_updates
    updates = []
    try:
        for name in os.listdir(library):
            folder = os.path.join(library, name)
            if name.startswith(".") or not os.path.isdir(folder):
                continue
            newest = os.path.getmtime(folder)
            for root, _dirs, files in os.walk(folder):
                for filename in files:
                    try:
                        newest = max(newest, os.path.getmtime(os.path.join(root, filename)))
                    except OSError:
                        pass
            updates.append((name, folder, newest))
    except OSError:
        return []
    updates.sort(key=lambda item: item[2], reverse=True)
    _public_recent_cache = (time.monotonic(), library, updates)
    return updates


def refresh_recent_public_items(context) -> None:
    wm = context.window_manager
    source = list_recent_public_updates()
    current = [(item.name, item.path, item.mtime) for item in wm.no3d_public_recent_items]
    if current == source:
        return
    wm.no3d_public_recent_items.clear()
    for name, path, mtime in source:
        item = wm.no3d_public_recent_items.add()
        item.name, item.path, item.mtime = name, path, mtime


def elapsed_label(timestamp: float) -> str:
    age = max(0, time.time() - timestamp)
    if age < 60: return f"{int(age)}s"
    if age < 3600: return f"{int(age / 60)}m"
    if age < 86400: return f"{int(age / 3600)}h"
    return f"{int(age / 86400)}d"


class NO3D_PublicRecentItem(PropertyGroup):
    path: StringProperty()
    mtime: bpy.props.FloatProperty()


class NO3D_ChangelogLine(PropertyGroup):
    text: StringProperty(name="Release note line")


class NO3D_UL_changelog_lines(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.prop(item, "text", text="")


def ensure_changelog_editor(wm) -> None:
    if not wm.no3d_changelog_lines:
        wm.no3d_changelog_lines.add()


class NO3D_UL_public_updates(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        row = layout.row(align=True)
        op = row.operator("no3d.open_public_product_folder", text=item.name, icon='FILE_FOLDER', emboss=False)
        op.path = item.path
        row.label(text=elapsed_label(item.mtime))


class NO3D_OT_open_public_product_folder(Operator):
    bl_idname = "no3d.open_public_product_folder"
    bl_label = "Open Public Product Folder"
    path: StringProperty()

    def execute(self, _context):
        bpy.ops.wm.path_open(filepath=self.path)
        return {"FINISHED"}


class NO3D_OT_add_product_changelog(Operator):
    bl_idname = "no3d.add_product_changelog"
    bl_label = "Add Note"
    bl_description = "Append a dated changelog note to the selected public product"

    def execute(self, context):
        asset = _active_asset(context)
        product = _linked_product(asset.name) if asset else None
        ensure_changelog_editor(context.window_manager)
        note = "\n".join(line.text.rstrip() for line in context.window_manager.no3d_changelog_lines).strip()
        if not product or not note:
            self.report({"ERROR"}, "Select a linked product and enter a changelog note")
            return {"CANCELLED"}
        path = product.pop("_json_path")
        product.pop("_folder_path", None)
        product.setdefault("pending_changelog", []).append(note)
        dashboard = product.setdefault("dashboard", {})
        dashboard["release_notes_updated_at"] = date.today().isoformat()
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(product, handle, indent=2)
            handle.write("\n")
        context.window_manager.no3d_changelog_lines.clear()
        context.window_manager.no3d_changelog_lines.add()
        context.window_manager.no3d_public_status = "Release note queued for the next successful publish"
        self.report({"INFO"}, "Release note added to the next publication")
        return {"FINISHED"}


class NO3D_OT_add_changelog_line(Operator):
    bl_idname = "no3d.add_changelog_line"
    bl_label = "Add Line"

    def execute(self, context):
        context.window_manager.no3d_changelog_lines.add()
        context.window_manager.no3d_changelog_line_index = len(context.window_manager.no3d_changelog_lines) - 1
        return {"FINISHED"}


class NO3D_OT_remove_changelog_line(Operator):
    bl_idname = "no3d.remove_changelog_line"
    bl_label = "Remove Line"

    def execute(self, context):
        wm = context.window_manager
        if len(wm.no3d_changelog_lines) > 1:
            wm.no3d_changelog_lines.remove(wm.no3d_changelog_line_index)
            wm.no3d_changelog_line_index = min(wm.no3d_changelog_line_index, len(wm.no3d_changelog_lines) - 1)
        return {"FINISHED"}


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
        staged, stage_output = stage_linked_asset(asset)
        if not staged:
            self.report({"ERROR"}, stage_output[-240:])
            return {"CANCELLED"}
        ok, output = _run(["preview", "--product", linked["handle"]])
        match = PLAN_RE.search(output)
        if not ok or not match:
            self.report({"ERROR"}, (output[-240:] if output else "Preview failed"))
            return {"CANCELLED"}
        context.window_manager.no3d_public_publish_plan = match.group(1)
        context.window_manager.no3d_public_publish_product = linked.get("title", asset.name)
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
    bl_label = "Publish This Product"
    bl_description = "Publish the exact unchanged version represented by the reviewed plan"
    bl_options = {"REGISTER"}

    def invoke(self, context, _event):
        return context.window_manager.invoke_confirm(
            self, _event, title="Publish NO3D product update?",
            message="This uploads media/assets, updates the live catalog, and regenerates the member manifest.",
            confirm_text="Publish This Product",
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
        context.window_manager.no3d_public_publish_product = ""
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
    NO3D_PublicRecentItem,
    NO3D_ChangelogLine,
    NO3D_UL_public_updates,
    NO3D_UL_changelog_lines,
    NO3D_OT_open_public_product_folder,
    NO3D_OT_add_product_changelog,
    NO3D_OT_add_changelog_line,
    NO3D_OT_remove_changelog_line,
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
    bpy.types.WindowManager.no3d_public_publish_product = StringProperty(default="")
    bpy.types.WindowManager.no3d_changelog_lines = CollectionProperty(type=NO3D_ChangelogLine)
    bpy.types.WindowManager.no3d_changelog_line_index = IntProperty(default=0)
    bpy.types.WindowManager.no3d_changelog_expanded = BoolProperty(default=False)
    bpy.types.WindowManager.no3d_show_public_updates = BoolProperty(default=True)
    bpy.types.WindowManager.no3d_public_recent_items = CollectionProperty(type=NO3D_PublicRecentItem)
    bpy.types.WindowManager.no3d_public_recent_index = IntProperty(default=0)
    if _stage_linked_on_save not in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.append(_stage_linked_on_save)


def unregister():
    try:
        bpy.app.handlers.save_post.remove(_stage_linked_on_save)
    except ValueError:
        pass
    for name in (
        "no3d_public_recent_index", "no3d_public_recent_items", "no3d_show_public_updates",
        "no3d_changelog_expanded", "no3d_changelog_line_index", "no3d_changelog_lines",
        "no3d_public_publish_product",
        "no3d_public_publish_plan", "no3d_public_status",
    ):
        try:
            delattr(bpy.types.WindowManager, name)
        except AttributeError:
            pass
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
