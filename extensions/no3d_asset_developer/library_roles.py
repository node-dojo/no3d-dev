"""Stable marker reader for Blender-facing NO3D library roles."""

import json
from pathlib import Path

MARKER_FILENAME = ".no3d-library.json"
SCHEMA = "no3d.library-marker/v0.1"
WIP_ID = "no3d.library.authoring.wip.v1"
STAGED_ID = "no3d.library.staged.catalog.v1"
WIP_DISPLAY_NAME = "NO3D - WIP"
STAGED_DISPLAY_NAME = "NO3D - STAGED"


def read_marker(root: str) -> dict | None:
    path = Path(root) / MARKER_FILENAME
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def require_role(root: str, library_id: str, role: str) -> dict:
    marker = read_marker(root)
    if not marker:
        raise ValueError(f"NO3D library marker is missing or invalid: {root}")
    if marker.get("schema_version") != SCHEMA:
        raise ValueError(f"Unsupported NO3D library marker schema: {root}")
    if marker.get("library_id") != library_id or marker.get("role") != role:
        raise ValueError(f"NO3D library role mismatch: expected {role}")
    if not marker.get("verified_at"):
        raise ValueError(f"NO3D library marker is unverified: {root}")
    return marker


def require_wip(root: str) -> dict:
    return require_role(root, WIP_ID, "wip")


def require_staged(root: str) -> dict:
    return require_role(root, STAGED_ID, "staged")


def ensure_registration(asset_libraries, display_name: str, root: str, library_id: str, role: str):
    """Register one validated path and refuse display/path ambiguity."""
    require_role(root, library_id, role)
    resolved = str(Path(root).resolve())
    by_name = [library for library in asset_libraries if library.name == display_name]
    if any(str(Path(library.path).resolve()) != resolved for library in by_name):
        raise ValueError(f"Blender library name is already bound to another root: {display_name}")
    by_path = [library for library in asset_libraries if str(Path(library.path).resolve()) == resolved]
    if len(by_path) > 1:
        raise ValueError(f"Blender library path is registered more than once: {root}")
    if by_path:
        by_path[0].name = display_name
        return by_path[0]
    if by_name:
        return by_name[0]
    return asset_libraries.new(name=display_name, directory=resolved)
