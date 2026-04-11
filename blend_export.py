"""
No3d Asset Developer — Template-based .blend export.

Spawns a background Blender subprocess that opens _export_template.blend,
appends the target asset from the source file, strips smuggled assets,
and saves a clean individual .blend.
"""

import logging
import os
import subprocess
import sys

import bpy

log = logging.getLogger(__name__)


def _get_addon_dir() -> str:
    """Return the directory containing this module."""
    return os.path.dirname(os.path.abspath(__file__))


def _asset_type_name(asset) -> str:
    """Map a Blender data-block type to the category string used by the
    subprocess append script (Object, Material, NodeTree, Collection)."""
    type_name = type(asset).__name__
    mapping = {
        "Object": "Object",
        "Material": "Material",
        "ShaderNodeTree": "NodeTree",
        "GeometryNodeTree": "NodeTree",
        "NodeTree": "NodeTree",
        "Collection": "Collection",
    }
    return mapping.get(type_name, type_name)


def export_asset_blend(
    asset,
    source_filepath: str,
    output_path: str,
) -> tuple[bool, int, str | None]:
    """Export a single asset to *output_path* via a background subprocess.

    Parameters
    ----------
    asset : bpy ID data-block
        The asset to export (must have ``asset_data``).
    source_filepath : str
        Absolute path to the current .blend file (``bpy.data.filepath``).
    output_path : str
        Absolute path for the resulting .blend file.

    Returns
    -------
    tuple[bool, int, str | None]
        ``(success, file_size_bytes, error_message)``.
    """
    addon_dir = _get_addon_dir()
    asset_name = asset.name
    asset_type = _asset_type_name(asset)

    template_path = os.path.join(addon_dir, "_export_template.blend")
    script_path = os.path.join(addon_dir, "_export_single_asset.py")
    blender_bin = bpy.app.binary_path

    # Validate paths
    if not os.path.isfile(script_path):
        msg = f"Export script not found: {script_path}"
        log.error(msg)
        return False, 0, msg

    if not source_filepath or not os.path.isfile(source_filepath):
        msg = f"Source .blend file not found: {source_filepath}"
        log.error(msg)
        return False, 0, msg

    # Template fallback: if _export_template.blend is missing, the subprocess
    # script handles creating a fresh default scene (factory settings + units).
    use_template = os.path.isfile(template_path)
    if not use_template:
        log.warning(
            "Template .blend not found at %s — subprocess will create a "
            "fresh default scene as fallback.",
            template_path,
        )

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Build command — --factory-startup prevents user addons from loading
    # in the subprocess, which avoids crashes from addon conflicts
    cmd = [
        blender_bin,
        "--factory-startup",
        "--background",
    ]
    if use_template:
        cmd.append(template_path)
    cmd.extend([
        "--python", script_path,
        "--",
        "--source", source_filepath,
        "--asset", asset_name,
        "--asset-type", asset_type,
        "--output", output_path,
    ])
    if not use_template:
        cmd.append("--no-template")

    log.info("Exporting '%s' (%s) via subprocess", asset_name, asset_type)
    log.info("Command: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip() if result.stderr else "(no stderr)"
            stdout = result.stdout.strip() if result.stdout else "(no stdout)"
            msg = (
                f"Subprocess exited with code {result.returncode}.\n"
                f"stdout: {stdout}\nstderr: {stderr}"
            )
            log.error(msg)
            return False, 0, msg
    except subprocess.TimeoutExpired:
        msg = f"Subprocess timed out (60 s) exporting '{asset_name}'"
        log.error(msg)
        return False, 0, msg
    except OSError as exc:
        msg = f"Failed to spawn Blender subprocess: {exc}"
        log.error(msg)
        return False, 0, msg

    # Verify output
    if not os.path.isfile(output_path):
        msg = f"Output file was not created: {output_path}"
        log.error(msg)
        return False, 0, msg

    file_size = os.path.getsize(output_path)
    if file_size == 0:
        msg = f"Output file is empty: {output_path}"
        log.error(msg)
        return False, 0, msg

    log.info(
        "Successfully exported '%s' — %d bytes written to %s",
        asset_name,
        file_size,
        output_path,
    )
    return True, file_size, None
