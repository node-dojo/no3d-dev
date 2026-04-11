"""
No3d Asset Developer — Session note manager.

Stores timestamped developer notes per-asset during a Blender session.
Notes are exported to markdown when assets are exported.
"""

import logging
import os
from datetime import datetime

import bpy
from bpy.props import StringProperty, CollectionProperty, IntProperty
from bpy.types import PropertyGroup

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Session-scoped storage (module-level, not saved to .blend)
# ---------------------------------------------------------------------------

_session_notes: dict[str, list[tuple[str, str]]] = {}
# asset_name -> [(timestamp_str, text), ...]


def add_note(asset_name: str, text: str) -> None:
    """Append a timestamped note for *asset_name*."""
    if not text.strip():
        return
    timestamp = datetime.now().strftime("%H:%M")
    _session_notes.setdefault(asset_name, []).append((timestamp, text.strip()))
    log.info("Note added for '%s' at %s", asset_name, timestamp)


def get_notes(asset_name: str) -> list[tuple[str, str]]:
    """Return list of ``(timestamp, text)`` for *asset_name*."""
    return list(_session_notes.get(asset_name, []))


def clear_notes(asset_name: str) -> None:
    """Remove all notes for *asset_name*."""
    if asset_name in _session_notes:
        del _session_notes[asset_name]
        log.info("Cleared notes for '%s'", asset_name)


def get_all_asset_names() -> list[str]:
    """Return asset names that have at least one note."""
    return [k for k, v in _session_notes.items() if v]


def has_notes(asset_name: str) -> bool:
    """Return True if *asset_name* has any notes."""
    return bool(_session_notes.get(asset_name))


def export_notes(asset_name: str, target_dir: str, overwrite: bool = True) -> str | None:
    """Write ``notes_{asset_name}.md`` into *target_dir*.

    Returns the written file path, or ``None`` if there are no notes.
    """
    notes = get_notes(asset_name)
    if not notes:
        return None

    os.makedirs(target_dir, exist_ok=True)
    filepath = os.path.join(target_dir, f"notes_{asset_name}.md")
    if os.path.isfile(filepath) and not overwrite:
        log.info(
            "Skipping notes overwrite for '%s' (existing file: %s)",
            asset_name,
            filepath,
        )
        return filepath

    today = datetime.now().strftime("%Y-%m-%d")
    lines: list[str] = [
        "---",
        f'asset: "{asset_name}"',
        f'created: {today}',
        "source: blender",
        "status: unprocessed",
        "---",
        "",
        "## Dev Notes",
        "",
    ]
    for ts, text in notes:
        lines.append(f"- [{ts}] {text}")

    lines.append("")  # trailing newline

    with open(filepath, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    log.info("Exported %d note(s) for '%s' to %s", len(notes), asset_name, filepath)
    return filepath


# ---------------------------------------------------------------------------
# Blender property group used by the UI for the text input field
# ---------------------------------------------------------------------------

class NO3D_PG_note_input(PropertyGroup):
    text: StringProperty(
        name="Note",
        description="Quick dev note for the active asset",
        default="",
    )


# ---------------------------------------------------------------------------
# Register / Unregister
# ---------------------------------------------------------------------------

def register():
    bpy.utils.register_class(NO3D_PG_note_input)
    bpy.types.WindowManager.no3d_note_input = bpy.props.PointerProperty(
        type=NO3D_PG_note_input
    )


def unregister():
    try:
        del bpy.types.WindowManager.no3d_note_input
    except AttributeError:
        pass
    bpy.utils.unregister_class(NO3D_PG_note_input)
