"""
No3d Asset Developer v3.0 — Two named extraction methods.

Method A (TEMPLATE_APPEND)
    Headless Blender subprocess. Opens _export_template.blend (preserves Scene,
    METRIC/mm units, color management), appends the named asset, strips smuggled
    asset markings, purges orphans, saves compressed.
    Delegates to the existing ``blend_export.export_asset_blend`` implementation.

Method B (DATABLOCK_WRITE)
    In-process one-liner. Uses ``bpy.data.libraries.write({asset}, ...)``, the
    native API that Blender's bundled ``scripts/startup/bl_operators/assets.py``
    and the pose-asset export template use to serialize a single ID block.
    No subprocess, no template file. Output has no Scene (units lost when opened
    standalone). Transitive dependencies are pulled along silently.

Both methods write a .blend at ``output_path`` and return a uniform result tuple:
    (success: bool, size_bytes: int, error: str | None, warnings: list[str])
"""

from __future__ import annotations

import logging
import os

import bpy

from . import blend_export

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Method A — Template Append (subprocess)
#
# RETAINED BUT NOT USER-EXPOSED (as of v3.0.x): the UI picker was removed and
# Method B is the sole exposed pipeline. This code is kept intact and remains
# reachable through the dispatcher when `wm.no3d_extraction_method` is set to
# 'TEMPLATE_APPEND' (e.g. from the Python console).
# ---------------------------------------------------------------------------

def method_a_template_append(
    asset,
    source_filepath: str,
    output_path: str,
) -> tuple[bool, int, str | None, list[str]]:
    """Run the v2 Template Append pipeline in a headless subprocess."""
    ok, size, err = blend_export.export_asset_blend(asset, source_filepath, output_path)
    warnings: list[str] = []
    if ok and os.path.isfile(source_filepath):
        src_size = os.path.getsize(source_filepath)
        if src_size > 0 and abs(size - src_size) / src_size < 0.05:
            warnings.append(
                f"Output .blend ({size:,} B) is within 5% of workbench size "
                f"({src_size:,} B) — export may have saved the workbench itself."
            )
        if size > 50 * 1024 * 1024:
            warnings.append(f"Output .blend is {size / 1024 / 1024:.1f} MB — cleanup may have failed.")
    return ok, size, err, warnings


# ---------------------------------------------------------------------------
# Method B — Datablock Write (in-process, pose-library-native)
# ---------------------------------------------------------------------------

def method_b_datablock_write(
    asset,
    output_path: str,
) -> tuple[bool, int, str | None, list[str]]:
    """Serialize *asset* to *output_path* via ``bpy.data.libraries.write``.

    This is the same API Blender uses internally for pose-asset export and the
    Mark-as-Asset "Create Asset From Selection" flow. It writes the datablock
    plus its transitive dependencies to a new .blend. Does not mutate the live
    session.
    """
    if asset is None:
        return False, 0, "No asset provided", []

    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
    except OSError as exc:
        return False, 0, f"Could not create output directory: {exc}", []

    # Pre-count smuggled assets (other data blocks marked as assets) so the caller
    # can report how many came along for the ride. We do NOT mutate them — that
    # would dirty the user's live workbench.
    warnings: list[str] = []
    smuggled: list[str] = []
    target_id = id(asset)
    for col in (bpy.data.objects, bpy.data.materials,
                bpy.data.node_groups, bpy.data.collections,
                bpy.data.worlds, bpy.data.brushes, bpy.data.actions):
        for block in col:
            if id(block) == target_id:
                continue
            if getattr(block, "asset_data", None) is not None:
                smuggled.append(f"{type(block).__name__}:{block.name}")

    if smuggled:
        warnings.append(
            f"{len(smuggled)} other asset(s) in workbench may come along as "
            f"transitive deps: {', '.join(smuggled[:5])}"
            + (f" (+{len(smuggled) - 5} more)" if len(smuggled) > 5 else "")
        )

    try:
        bpy.data.libraries.write(
            output_path,
            {asset},
            fake_user=True,
            compress=True,
            path_remap='NONE',
        )
    except Exception as exc:
        log.error("libraries.write failed for '%s': %s", getattr(asset, "name", "?"), exc)
        return False, 0, f"libraries.write failed: {exc}", warnings

    if not os.path.isfile(output_path):
        return False, 0, f"Output file was not created: {output_path}", warnings

    size = os.path.getsize(output_path)
    if size == 0:
        return False, 0, f"Output file is empty: {output_path}", warnings

    log.info("Method B wrote '%s' (%d bytes) to %s", asset.name, size, output_path)
    return True, size, None, warnings


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def extract(
    method: str,
    asset,
    source_filepath: str,
    output_path: str,
) -> tuple[bool, int, str | None, list[str]]:
    """Route to the chosen method. *method* is the EnumProperty identifier."""
    if method == "TEMPLATE_APPEND":
        return method_a_template_append(asset, source_filepath, output_path)
    if method == "DATABLOCK_WRITE":
        return method_b_datablock_write(asset, output_path)
    return False, 0, f"Unknown extraction method: {method}", []
