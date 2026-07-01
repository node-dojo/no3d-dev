"""
No3d Asset Developer — WIP auto-sync.

Keeps a {wip_folder}/{AssetName}/ directory mirrored against every datablock
marked as an asset in the current .blend. Triggers:

    * Mark as Asset      depsgraph diff -> sync_one(new_asset)
    * Rename             depsgraph diff -> rename_folder(old, new)
    * File save          save_post handler -> sync_changed()
    * Manual button      operators.NO3D_OT_sync_wip_all -> sync_all()

The .blend and thumbnail are always overwritten on sync; frontmatter and notes
files are preserved (they hold curated content that should not be clobbered by
an auto-trigger). State is tracked in {wip_folder}/.no3d-wip-state.json.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Iterable

import bpy
from bpy.app.handlers import persistent

from . import extraction_methods
from . import utils
from .notes import note_manager

log = logging.getLogger(__name__)

STATE_FILENAME = ".no3d-wip-state.json"
DEBOUNCE_SECONDS = 0.2

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

# Snapshot of marked asset names from the previous depsgraph tick. Used to
# detect Mark / Unmark / Rename without polling. Seeded lazily — bpy.data is
# restricted at addon-register time, so we initialize on the first tick.
_last_asset_names: set[str] | None = None
_last_depsgraph_tick: float = 0.0
_last_sync_summary: dict = {"count": 0, "ts": 0.0, "msg": ""}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wm_get(name: str, default=None):
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return default
    return getattr(wm, name, default)


def get_wip_folder() -> str:
    """Resolve the configured WIP folder, or '' if unset."""
    path = _wm_get("no3d_wip_folder", "") or ""
    if not path:
        # Fall back to addon preferences if WM prop not yet seeded.
        addon = bpy.context.preferences.addons.get("no3d_asset_developer")
        if addon and hasattr(addon, "preferences"):
            path = getattr(addon.preferences, "export_library_path", "") or ""
    return bpy.path.abspath(path) if path else ""


def _is_auto_enabled(flag: str) -> bool:
    return bool(_wm_get(flag, True))


def _current_asset_names() -> set[str]:
    return {a.name for a in utils.get_all_visible_assets(None, "ALL")}


def _asset_by_name(name: str):
    for asset in utils.get_all_visible_assets(None, "ALL"):
        if asset.name == name:
            return asset
    return None


def _state_path(wip_folder: str) -> str:
    return os.path.join(wip_folder, STATE_FILENAME)


def _load_state(wip_folder: str) -> dict:
    path = _state_path(wip_folder)
    if not os.path.isfile(path):
        return {"assets": {}}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or "assets" not in data:
            return {"assets": {}}
        return data
    except (OSError, json.JSONDecodeError):
        return {"assets": {}}


def _save_state(wip_folder: str, state: dict) -> None:
    try:
        os.makedirs(wip_folder, exist_ok=True)
        with open(_state_path(wip_folder), "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
    except OSError as exc:
        log.warning("Could not write WIP state file: %s", exc)


def _record_sync(state: dict, asset_name: str) -> None:
    state.setdefault("assets", {})[asset_name] = {
        "synced_at": time.time(),
        "source_mtime": _source_mtime(),
    }


def _source_mtime() -> float:
    src = bpy.data.filepath
    if src and os.path.isfile(src):
        return os.path.getmtime(src)
    return 0.0


def _set_status(msg: str, count: int = 0) -> None:
    _last_sync_summary["count"] = count
    _last_sync_summary["ts"] = time.time()
    _last_sync_summary["msg"] = msg


def get_status() -> dict:
    return dict(_last_sync_summary)


def list_recent_folders(limit: int = 8) -> list[tuple[str, float]]:
    """Return up to *limit* (folder_name, mtime) pairs sorted newest-first.

    Looks at every subdirectory of the WIP folder. mtime reflects the most
    recent change inside the folder (its own mtime, which advances on file
    add/remove). Hidden folders and the state file are ignored.
    """
    wip_folder = get_wip_folder()
    if not wip_folder or not os.path.isdir(wip_folder):
        return []
    entries: list[tuple[str, float]] = []
    try:
        for name in os.listdir(wip_folder):
            if name.startswith("."):
                continue
            full = os.path.join(wip_folder, name)
            if not os.path.isdir(full):
                continue
            entries.append((name, os.path.getmtime(full)))
    except OSError:
        return []
    entries.sort(key=lambda e: e[1], reverse=True)
    return entries[:limit]


# ---------------------------------------------------------------------------
# Core sync
# ---------------------------------------------------------------------------

def _get_prefs_obj():
    addon = bpy.context.preferences.addons.get("no3d_asset_developer")
    return getattr(addon, "preferences", None) if addon else None


def sync_one(asset, wip_folder: str, prefs=None) -> tuple[bool, str]:
    """Extract a single asset into {wip_folder}/{asset.name}/.

    Always overwrites .blend and thumbnail; preserves frontmatter and notes.
    Returns (ok, message).
    """
    if not wip_folder:
        return False, "WIP folder not set"
    if asset is None or not getattr(asset, "asset_data", None):
        return False, "Not an asset"

    method = _wm_get("no3d_extraction_method", "DATABLOCK_WRITE")
    source = bpy.data.filepath
    if method == "TEMPLATE_APPEND" and not source:
        return False, "Save the .blend first (Method A requires a saved file)"

    asset_name = asset.name
    asset_folder = os.path.join(wip_folder, asset_name)
    try:
        os.makedirs(asset_folder, exist_ok=True)
    except OSError as exc:
        return False, f"Could not create folder: {exc}"

    output_path = os.path.join(asset_folder, f"{asset_name}.blend")
    ok, _size, err, _warns = extraction_methods.extract(method, asset, source, output_path)
    if not ok:
        return False, f"extract failed: {err}"

    # Thumbnail: always overwrite.
    try:
        utils.export_asset_thumbnail(asset, wip_folder, overwrite=True)
    except Exception as exc:
        log.warning("Thumbnail failed for '%s': %s", asset_name, exc)

    # Frontmatter: preserve existing (do not overwrite).
    try:
        if prefs is None:
            prefs = _get_prefs_obj()
        utils.generate_asset_frontmatter(asset, wip_folder, prefs, overwrite=False)
    except Exception as exc:
        log.warning("Frontmatter failed for '%s': %s", asset_name, exc)

    # Notes: preserve existing.
    if note_manager.has_notes(asset_name):
        try:
            note_manager.export_notes(asset_name, asset_folder, overwrite=False)
        except Exception as exc:
            log.warning("Notes failed for '%s': %s", asset_name, exc)

    state = _load_state(wip_folder)
    _record_sync(state, asset_name)
    _save_state(wip_folder, state)
    return True, f"synced '{asset_name}'"


def sync_all() -> tuple[int, int, list[str]]:
    """Sync every marked asset in the current file. Returns (ok, fail, errors)."""
    wip_folder = get_wip_folder()
    if not wip_folder:
        return 0, 0, ["WIP folder not set"]

    assets = utils.get_all_visible_assets(None, "ALL")
    prefs = _get_prefs_obj()
    ok_count = 0
    fail_count = 0
    errors: list[str] = []
    for asset in assets:
        ok, msg = sync_one(asset, wip_folder, prefs)
        if ok:
            ok_count += 1
        else:
            fail_count += 1
            errors.append(f"{asset.name}: {msg}")

    _set_status(f"Sync All: {ok_count} ok, {fail_count} fail", ok_count)
    return ok_count, fail_count, errors


def sync_changed() -> tuple[int, list[str]]:
    """Sync assets whose source has changed since last sync (used on save)."""
    wip_folder = get_wip_folder()
    if not wip_folder:
        return 0, []

    state = _load_state(wip_folder)
    src_mtime = _source_mtime()
    assets = utils.get_all_visible_assets(None, "ALL")
    prefs = _get_prefs_obj()

    synced = 0
    errors: list[str] = []
    for asset in assets:
        record = state.get("assets", {}).get(asset.name)
        last = record.get("source_mtime", 0.0) if record else 0.0
        # If never synced or source has advanced, re-sync.
        if last >= src_mtime > 0:
            continue
        ok, msg = sync_one(asset, wip_folder, prefs)
        if ok:
            synced += 1
        else:
            errors.append(f"{asset.name}: {msg}")

    if synced:
        _set_status(f"Save sync: {synced} updated", synced)
    return synced, errors


def rename_folder(old_name: str, new_name: str) -> bool:
    """Rename {wip}/{old}/ to {wip}/{new}/ and rename inner files.

    Returns True if the folder existed and was renamed; False otherwise.
    Inner files: {old}.blend, icon_{old}.png, desc_{old}.md, notes_{old}.md.
    """
    wip_folder = get_wip_folder()
    if not wip_folder:
        return False
    old_dir = os.path.join(wip_folder, old_name)
    new_dir = os.path.join(wip_folder, new_name)
    if not os.path.isdir(old_dir):
        return False
    if os.path.exists(new_dir):
        log.warning("Cannot rename: target folder already exists: %s", new_dir)
        return False

    try:
        os.rename(old_dir, new_dir)
    except OSError as exc:
        log.warning("Folder rename failed: %s", exc)
        return False

    # Rename inner files that include the asset name.
    rename_map = {
        f"{old_name}.blend": f"{new_name}.blend",
        f"icon_{old_name}.png": f"icon_{new_name}.png",
        f"desc_{old_name}.md": f"desc_{new_name}.md",
        f"notes_{old_name}.md": f"notes_{new_name}.md",
    }
    for old_file, new_file in rename_map.items():
        old_p = os.path.join(new_dir, old_file)
        new_p = os.path.join(new_dir, new_file)
        if os.path.isfile(old_p) and not os.path.exists(new_p):
            try:
                os.rename(old_p, new_p)
            except OSError as exc:
                log.warning("Inner rename %s -> %s failed: %s", old_p, new_p, exc)

    # Update state file.
    state = _load_state(wip_folder)
    assets = state.setdefault("assets", {})
    if old_name in assets:
        assets[new_name] = assets.pop(old_name)
        _save_state(wip_folder, state)
    return True


# ---------------------------------------------------------------------------
# Depsgraph diff (Mark / Unmark / Rename detection)
# ---------------------------------------------------------------------------

def _diff_and_react() -> None:
    """Compare current asset name set with the previous tick; act on changes."""
    global _last_asset_names

    current = _current_asset_names()
    # First tick after register/load: seed the snapshot, do nothing else.
    if _last_asset_names is None:
        _last_asset_names = current
        return
    if current == _last_asset_names:
        return

    added = current - _last_asset_names
    removed = _last_asset_names - current

    # Heuristic rename detection: when one is added and one is removed in the
    # same tick, treat it as a rename. With multiple, we cannot reliably pair
    # them — fall back to treating each as an add (the new folder is created;
    # the old folder is left in place; user can clean up manually).
    if len(added) == 1 and len(removed) == 1:
        old_name = next(iter(removed))
        new_name = next(iter(added))
        if _is_auto_enabled("no3d_wip_auto_rename"):
            if rename_folder(old_name, new_name):
                _set_status(f"Renamed '{old_name}' -> '{new_name}'", 1)
                _last_asset_names = current
                return
        # If rename folder didn't exist (asset was never synced), fall through
        # and treat as a fresh mark.

    if added and _is_auto_enabled("no3d_wip_auto_mark"):
        wip_folder = get_wip_folder()
        if wip_folder:
            prefs = _get_prefs_obj()
            ok = 0
            for name in added:
                asset = _asset_by_name(name)
                if asset is None:
                    continue
                success, _msg = sync_one(asset, wip_folder, prefs)
                if success:
                    ok += 1
            if ok:
                _set_status(f"Mark sync: {ok} new asset(s)", ok)

    _last_asset_names = current


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

@persistent
def _on_depsgraph_update(scene, depsgraph):
    """Cheap debounced check: only diff once per DEBOUNCE_SECONDS."""
    global _last_depsgraph_tick
    now = time.time()
    if now - _last_depsgraph_tick < DEBOUNCE_SECONDS:
        return
    _last_depsgraph_tick = now
    try:
        _diff_and_react()
    except Exception as exc:
        log.exception("WIP depsgraph handler failed: %s", exc)


@persistent
def _on_save_post(_dummy):
    """After save, re-sync any asset whose source has advanced."""
    if not _is_auto_enabled("no3d_wip_auto_save"):
        return
    try:
        sync_changed()
    except Exception as exc:
        log.exception("WIP save handler failed: %s", exc)


@persistent
def _on_load_post(_dummy):
    """Reset the asset-name snapshot so it re-seeds on the next depsgraph tick."""
    global _last_asset_names
    _last_asset_names = None


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register():
    # Snapshot is seeded lazily on the first depsgraph tick; bpy.data is
    # restricted here.
    global _last_asset_names
    _last_asset_names = None

    handlers = bpy.app.handlers
    if _on_depsgraph_update not in handlers.depsgraph_update_post:
        handlers.depsgraph_update_post.append(_on_depsgraph_update)
    if _on_save_post not in handlers.save_post:
        handlers.save_post.append(_on_save_post)
    if _on_load_post not in handlers.load_post:
        handlers.load_post.append(_on_load_post)


def unregister():
    handlers = bpy.app.handlers
    for handler_list, fn in (
        (handlers.depsgraph_update_post, _on_depsgraph_update),
        (handlers.save_post, _on_save_post),
        (handlers.load_post, _on_load_post),
    ):
        try:
            handler_list.remove(fn)
        except ValueError:
            pass
