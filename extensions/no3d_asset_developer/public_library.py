"""Blender controls for the canonical public NO3D product library."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from urllib.parse import quote
from datetime import date

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, CollectionProperty, IntProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup, UIList

from . import library_roles, wip_sync

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


def _linked_product(asset_or_name):
    asset = asset_or_name if not isinstance(asset_or_name, str) else None
    asset_name = asset.name if asset is not None else asset_or_name
    stable_product_id = str(asset.get("no3d_product_id", "")) if asset is not None else ""
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
            product_id = ((data.get("metadata") or {}).get("solvet") or {}).get("product_id", "")
            if (stable_product_id and product_id == stable_product_id) or asset_name in (
                data.get("handle"), data.get("title"),
                (data.get("dashboard") or {}).get("blender_asset_name"),
            ):
                if asset is not None and product_id and not stable_product_id:
                    asset["no3d_product_id"] = product_id
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


def _release_text_name(handle: str) -> str:
    return f"NO3D Release Notes — {handle}"


def _save_release_text(text) -> tuple[bool, str]:
    json_path = text.get("no3d_product_json", "")
    if not json_path or not os.path.isfile(json_path):
        return False, "The linked product JSON is unavailable"
    try:
        with open(json_path, "r", encoding="utf-8") as handle:
            product = json.load(handle)
        body = text.as_string().strip()
        product["pending_changelog"] = [body] if body else []
        product.setdefault("dashboard", {})["release_notes_updated_at"] = date.today().isoformat()
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(product, handle, indent=2)
            handle.write("\n")
        text["no3d_saved_body"] = body
        return True, "Release notes saved locally"
    except (OSError, json.JSONDecodeError) as exc:
        return False, str(exc)


def _save_text_for_product(product) -> tuple[bool, str]:
    text = bpy.data.texts.get(_release_text_name(product["handle"]))
    if text is None:
        return True, "No open release-note document"
    return _save_release_text(text)


def _clear_published_text(handle: str) -> None:
    text = bpy.data.texts.get(_release_text_name(handle))
    if text is not None:
        text.clear()
        text["no3d_saved_body"] = ""
        text["no3d_published"] = True


class NO3D_UL_public_updates(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        row = layout.row(align=True)
        op = row.operator("no3d.open_public_product_folder", text=item.name, icon='FILE_FOLDER', emboss=False)
        op.path = item.path
        row.label(text=elapsed_label(item.mtime))
        actions = row.operator("no3d.public_update_actions", text="", icon='DOWNARROW_HLT')
        actions.path = item.path


def _obsidian_url(vault: str, file_path: str = "") -> str:
    url = f"obsidian://open?vault={quote(vault, safe='')}"
    return f"{url}&file={quote(file_path, safe='')}" if file_path else url


def _open_url(url: str) -> None:
    subprocess.Popen(["/usr/bin/open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _product_file(folder: str, suffix: str) -> str:
    name = os.path.basename(folder.rstrip(os.sep))
    exact = os.path.join(folder, f"{name}{suffix}")
    if os.path.isfile(exact):
        return exact
    try:
        return next((os.path.join(folder, item) for item in os.listdir(folder) if item.endswith(suffix)), "")
    except OSError:
        return ""


class NO3D_OT_public_product_action(Operator):
    bl_idname = "no3d.public_product_action"
    bl_label = "Public Product Action"
    path: StringProperty()
    action: StringProperty()

    def execute(self, context):
        prefs = _prefs()
        if self.action == "finder":
            bpy.ops.wm.path_open(filepath=self.path)
        elif self.action == "canvas":
            canvas = _product_file(self.path, ".canvas")
            if not canvas:
                self.report({"ERROR"}, "Product canvas not found")
                return {"CANCELLED"}
            library_root = bpy.path.abspath(prefs.public_library_path).rstrip(os.sep)
            relative = os.path.relpath(canvas, os.path.dirname(library_root)).replace(os.sep, "/")
            _open_url(_obsidian_url(prefs.obsidian_library_vault_name, relative))
        elif self.action == "description":
            description = _product_file(self.path, "_desc.md")
            if not description:
                self.report({"ERROR"}, "Product description not found")
                return {"CANCELLED"}
            library_root = bpy.path.abspath(prefs.public_library_path).rstrip(os.sep)
            relative = os.path.relpath(description, os.path.dirname(library_root)).replace(os.sep, "/")
            _open_url(_obsidian_url(prefs.obsidian_library_vault_name, relative))
        elif self.action == "json":
            json_path = _product_file(self.path, ".json")
            if json_path:
                subprocess.Popen(["/usr/bin/open", json_path])
        elif self.action == "copy_path":
            context.window_manager.clipboard = self.path
        return {"FINISHED"}


def _draw_product_actions(layout, path: str) -> None:
    for action, label, icon in (
        ("finder", "Open Product Folder in Finder", 'FILE_FOLDER'),
        ("canvas", "Open Product Canvas in Obsidian", 'FILE'),
        ("description", "Open Description in Obsidian", 'TEXT'),
        ("json", "Open Product JSON", 'PRESET'),
        ("copy_path", "Copy Product Path", 'COPYDOWN'),
    ):
        op = layout.operator("no3d.public_product_action", text=label, icon=icon)
        op.path, op.action = path, action


class NO3D_OT_public_update_actions(Operator):
    bl_idname = "no3d.public_update_actions"
    bl_label = "Product Actions"
    path: StringProperty()

    def invoke(self, context, _event):
        path = self.path
        context.window_manager.popup_menu(
            lambda menu, _ctx: _draw_product_actions(menu.layout, path),
            title=os.path.basename(path), icon='ASSET_MANAGER',
        )
        return {"FINISHED"}


class NO3D_OT_open_obsidian_bookmark(Operator):
    bl_idname = "no3d.open_obsidian_bookmark"
    bl_label = "Open Obsidian Bookmark"
    bookmark: StringProperty()

    def execute(self, _context):
        prefs = _prefs()
        targets = {
            "vault": (prefs.obsidian_library_vault_name, ""),
            "workbench": (prefs.obsidian_library_vault_name, prefs.obsidian_workbench_path),
            "workflow": (prefs.obsidian_docs_vault_name, prefs.obsidian_catalog_docs_path),
            "add": (prefs.obsidian_docs_vault_name, "NO3D/docs/Quick Guide - Add a NO3D Product.md"),
            "edit": (prefs.obsidian_docs_vault_name, "NO3D/docs/Quick Guide - Edit a NO3D Product.md"),
        }
        vault, path = targets[self.bookmark]
        _open_url(_obsidian_url(vault, path))
        return {"FINISHED"}


def draw_button_context_menu(self, context):
    button = getattr(context, "button_operator", None)
    if button is None or getattr(button, "bl_idname", "") not in {
        "NO3D_OT_open_public_product_folder", "no3d.open_public_product_folder",
    }:
        return
    self.layout.separator()
    _draw_product_actions(self.layout, button.path)


class NO3D_OT_open_public_product_folder(Operator):
    bl_idname = "no3d.open_public_product_folder"
    bl_label = "Open Public Product Folder"
    path: StringProperty()

    def execute(self, _context):
        bpy.ops.wm.path_open(filepath=self.path)
        return {"FINISHED"}


class NO3D_OT_edit_release_notes(Operator):
    bl_idname = "no3d.edit_release_notes"
    bl_label = "Edit Next Release Notes"
    bl_description = "Open product-bound pending release notes in Blender's native Text Editor"

    def execute(self, context):
        asset = _active_asset(context)
        product = _linked_product(asset) if asset else None
        if not product:
            self.report({"ERROR"}, "Select a linked public product")
            return {"CANCELLED"}
        name = _release_text_name(product["handle"])
        text = bpy.data.texts.get(name) or bpy.data.texts.new(name)
        pending = "\n\n".join(str(note) for note in (product.get("pending_changelog") or []))
        if "no3d_product_json" not in text:
            text.write(pending)
            text["no3d_saved_body"] = pending
        text["no3d_product_handle"] = product["handle"]
        text["no3d_product_title"] = product.get("title", asset.name)
        text["no3d_product_json"] = product["_json_path"]
        text["no3d_published"] = False

        existing_windows = {window.as_pointer() for window in context.window_manager.windows}
        try:
            bpy.ops.screen.area_dupli('INVOKE_DEFAULT')
        except RuntimeError:
            self.report({"WARNING"}, "Release-note text created; open a Text Editor to edit it")
            return {"FINISHED"}

        attempts = [0]
        def configure_text_window():
            attempts[0] += 1
            for window in bpy.context.window_manager.windows:
                if window.as_pointer() in existing_windows:
                    continue
                area = window.screen.areas[0] if window.screen.areas else None
                if area:
                    area.type = 'TEXT_EDITOR'
                    area.spaces.active.text = text
                    return None
            return 0.1 if attempts[0] < 20 else None
        bpy.app.timers.register(configure_text_window, first_interval=0.1)
        return {"FINISHED"}


class NO3D_OT_save_release_notes(Operator):
    bl_idname = "no3d.save_release_notes"
    bl_label = "Save Release Notes"

    def execute(self, context):
        text = getattr(context.space_data, "text", None)
        if text is None or "no3d_product_json" not in text:
            self.report({"ERROR"}, "This is not a NO3D release-note document")
            return {"CANCELLED"}
        ok, message = _save_release_text(text)
        self.report({"INFO" if ok else "ERROR"}, message)
        return {"FINISHED" if ok else "CANCELLED"}


class NO3D_PT_release_notes_editor(Panel):
    bl_label = "NO3D Release Notes"
    bl_idname = "NO3D_PT_release_notes_editor"
    bl_space_type = 'TEXT_EDITOR'
    bl_region_type = 'UI'
    bl_category = "NO3D"

    @classmethod
    def poll(cls, context):
        text = getattr(context.space_data, "text", None)
        return text is not None and "no3d_product_json" in text

    def draw(self, context):
        text = context.space_data.text
        self.layout.label(text=f"Product: {text.get('no3d_product_title', '')}")
        self.layout.label(text="Release: Next publication")
        self.layout.operator("no3d.save_release_notes", icon='FILE_TICK')


def _run(args: list[str]) -> tuple[bool, str]:
    repo, library, workflow = _paths()
    if not repo or not os.path.isdir(repo):
        return False, "SOLVET repository is not configured"
    if not library or not os.path.isdir(library):
        return False, "Public product library is not configured"
    try:
        library_roles.require_staged(library)
    except ValueError as exc:
        return False, str(exc)
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
    linked = _linked_product(asset)
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
    product_id = ((linked.get("metadata") or {}).get("solvet") or {}).get("product_id")
    ok, output = _run(["stage", "--asset-name", asset.name, "--product", product_id or linked["handle"], "--source-folder", source])
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
        try:
            receipt = next(json.loads(line) for line in reversed(output.splitlines()) if line.startswith("{"))
            if receipt.get("product_id"):
                asset["no3d_product_id"] = receipt["product_id"]
        except (StopIteration, json.JSONDecodeError):
            pass
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
    bl_label = "Share / Publish — Review"
    bl_description = "Run read-only remote checks and create a content-bound publish plan"
    bl_options = {"REGISTER"}

    def execute(self, context):
        asset = _active_asset(context)
        if not asset:
            self.report({"ERROR"}, "Select a marked asset first")
            return {"CANCELLED"}
        linked = _linked_product(asset)
        if not linked:
            self.report({"ERROR"}, "Promote this asset to a public draft first")
            return {"CANCELLED"}
        saved, save_message = _save_text_for_product(linked)
        if not saved:
            self.report({"ERROR"}, save_message)
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
        linked = _linked_product(asset) if asset else None
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
    bl_label = "Share / Publish"
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
        asset = _active_asset(context)
        linked = _linked_product(asset) if asset else None
        reviewed_product = context.window_manager.no3d_public_publish_product
        if not linked or linked.get("title", asset.name) != reviewed_product:
            self.report({"ERROR"}, f"This plan belongs to {reviewed_product or 'another product'}")
            return {"CANCELLED"}
        ok, output = _run(["publish", "--plan", plan])
        if not ok:
            context.window_manager.no3d_public_status = "Publish incomplete; see console and review again"
            self.report({"ERROR"}, output[-240:] or "Publish failed")
            return {"CANCELLED"}
        if linked:
            _clear_published_text(linked["handle"])
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
    if asset and _linked_product(asset):
        try:
            stage_linked_asset(asset, quiet=True, export_first=False)
        except Exception:
            log.exception("Could not auto-stage linked public asset")


@persistent
def _save_release_texts_on_save(_dummy):
    for text in bpy.data.texts:
        if "no3d_product_json" in text and text.as_string().strip() != text.get("no3d_saved_body", ""):
            ok, message = _save_release_text(text)
            if not ok:
                log.error("Could not save %s: %s", text.name, message)


_classes = (
    NO3D_PublicRecentItem,
    NO3D_UL_public_updates,
    NO3D_OT_open_public_product_folder,
    NO3D_OT_public_product_action,
    NO3D_OT_public_update_actions,
    NO3D_OT_open_obsidian_bookmark,
    NO3D_OT_edit_release_notes,
    NO3D_OT_save_release_notes,
    NO3D_PT_release_notes_editor,
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
    bpy.types.WindowManager.no3d_show_public_updates = BoolProperty(default=True)
    bpy.types.WindowManager.no3d_show_obsidian_links = BoolProperty(default=False)
    bpy.types.WindowManager.no3d_public_recent_items = CollectionProperty(type=NO3D_PublicRecentItem)
    bpy.types.WindowManager.no3d_public_recent_index = IntProperty(default=0)
    if _save_release_texts_on_save not in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.append(_save_release_texts_on_save)
    if _stage_linked_on_save not in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.append(_stage_linked_on_save)
    bpy.types.UI_MT_button_context_menu.append(draw_button_context_menu)


def unregister():
    try:
        bpy.types.UI_MT_button_context_menu.remove(draw_button_context_menu)
    except (ValueError, AttributeError):
        pass
    try:
        bpy.app.handlers.save_post.remove(_stage_linked_on_save)
    except ValueError:
        pass
    try:
        bpy.app.handlers.save_post.remove(_save_release_texts_on_save)
    except ValueError:
        pass
    for name in (
        "no3d_public_recent_index", "no3d_public_recent_items", "no3d_show_public_updates", "no3d_show_obsidian_links",
        "no3d_public_publish_product",
        "no3d_public_publish_plan", "no3d_public_status",
    ):
        try:
            delattr(bpy.types.WindowManager, name)
        except AttributeError:
            pass
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
