"""
repo_registration
=================
Self-registers the NO3D extensions repository in Blender's user preferences
so installs of this add-on receive updates through Blender's native
Get Extensions system -- including copies originally installed from a
Gumroad zip via "Install from Disk".

Behavior:
  * Idempotent: if a repo with REMOTE_URL already exists, do nothing.
  * Deferred: preferences can't be safely mutated inside register()
    (restricted context), so the work runs once via bpy.app.timers.
  * Respectful: runs only once per install (marker file in the user config
    dir). If the user deletes the repo afterwards, we do NOT re-add it.
"""

import os

import bpy

REPO_NAME = "NO3D Tools"
REPO_MODULE = "no3d_tools"
REMOTE_URL = "https://node-dojo.github.io/no3d-asset-developer/index.json"

_MARKER = "no3d_repo_registered"


def _marker_path() -> str:
    cfg = bpy.utils.user_resource("CONFIG")
    return os.path.join(cfg, _MARKER)


def _already_ran_once() -> bool:
    try:
        return os.path.exists(_marker_path())
    except Exception:
        return False


def _write_marker() -> None:
    try:
        path = _marker_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(REMOTE_URL + "\n")
    except Exception:
        pass  # cosmetic only; worst case we try again next session


def _repo_exists() -> bool:
    repos = bpy.context.preferences.extensions.repos
    return any(r.remote_url == REMOTE_URL for r in repos)


def _ensure_repo() -> None:
    """Add the NO3D repo to user preferences (runs in a safe, full context)."""
    if _repo_exists():
        _write_marker()
        return

    repos = bpy.context.preferences.extensions.repos
    repo = repos.new(
        name=REPO_NAME,
        module=REPO_MODULE,
        remote_url=REMOTE_URL,
    )
    repo.enabled = True
    repo.use_sync_on_startup = True
    _write_marker()

    # Persist so the repo survives even if the user never hits Save
    # Preferences. Respect users who manage prefs manually.
    if bpy.context.preferences.use_preferences_save:
        try:
            bpy.ops.wm.save_userpref()
        except Exception:
            pass

    print("[no3d_asset_developer] Registered update repository: %s" % REMOTE_URL)


def _deferred() -> None:
    """Timer callback: preferences are writable here. Return None = one-shot."""
    try:
        _ensure_repo()
    except Exception as exc:  # never let this break the add-on
        print("[no3d_asset_developer] repo registration skipped: %r" % exc)
    return None


def register() -> None:
    # Only ever auto-add once per install; a user who removed the repo has
    # made a choice we honor.
    if _already_ran_once():
        return
    if not bpy.app.timers.is_registered(_deferred):
        bpy.app.timers.register(_deferred, first_interval=1.0)


def unregister() -> None:
    if bpy.app.timers.is_registered(_deferred):
        bpy.app.timers.unregister(_deferred)
