# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent Bridge's own registry: JSON files at ~/.blender-pairs/<pid>.json.

Standalone and bpy-free (runs in the headless MCP subprocess). Shares only the
on-disk FORMAT with other writers — no code dependency on any Blender add-on.
"""

import json
import os
import time
from pathlib import Path

REGISTRY_DIR = Path.home() / ".blender-pairs"


def _path_for_pid(pid: int) -> Path:
    return REGISTRY_DIR / f"{pid}.json"


def write(pid: int, data: dict) -> Path:
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    path = _path_for_pid(pid)
    payload = dict(data)
    payload.setdefault("blender_pid", pid)
    payload.setdefault("started_at", time.time())
    path.write_text(json.dumps(payload, indent=2))
    return path


def read(pid: int) -> dict | None:
    path = _path_for_pid(pid)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def remove(pid: int) -> bool:
    try:
        _path_for_pid(pid).unlink()
        return True
    except FileNotFoundError:
        return False


def list_all() -> list[dict]:
    if not REGISTRY_DIR.exists():
        return []
    out = []
    for path in sorted(REGISTRY_DIR.glob("*.json")):
        try:
            out.append(json.loads(path.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def gc_dead() -> list[int]:
    cleaned = []
    for entry in list_all():
        pid = entry.get("blender_pid")
        if not isinstance(pid, int):
            continue
        if not _pid_alive(pid):
            if remove(pid):
                cleaned.append(pid)
    return cleaned


def stem_of(entry: dict) -> str:
    stem = entry.get("blendfile_stem")
    if stem:
        return str(stem)
    bf = entry.get("blendfile")
    if bf:
        return Path(bf).stem
    return ""


def live_instances() -> list[dict]:
    gc_dead()
    return list_all()
