"""
No3d Asset Developer — Subprocess export script.

Executed by Blender in ``--background`` mode.  Opens the export template
(or a factory-default scene), appends the target asset from the source
file, strips smuggled asset markings, purges orphans, and saves.

Usage (invoked by blend_export.py — not called directly):

    blender --background _export_template.blend --python _export_single_asset.py \
        -- --source "/path/to/source.blend" \
           --asset "Dojo Support Bracket" \
           --asset-type "Object" \
           --output "/path/to/output/Dojo Support Bracket.blend"
"""

import argparse
import os
import sys

# ``bpy`` is available because Blender is the host interpreter.
import bpy  # noqa: E402


def _parse_args() -> argparse.Namespace:
    """Parse arguments after the ``--`` separator."""
    argv = sys.argv
    try:
        idx = argv.index("--")
    except ValueError:
        print("ERROR: No '--' separator found in command-line arguments.", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Export a single asset from a .blend file")
    parser.add_argument("--source", required=True, help="Path to source .blend file")
    parser.add_argument("--asset", required=True, help="Name of the asset to export")
    parser.add_argument("--asset-type", required=True,
                        help="Blender data category: Object, Material, NodeTree, Collection")
    parser.add_argument("--output", required=True, help="Output .blend file path")
    parser.add_argument("--no-template", action="store_true",
                        help="No template was loaded — create factory scene first")
    return parser.parse_args(argv[idx + 1:])


# Map asset-type CLI argument to bpy.ops.wm.append directory segment
_APPEND_DIRS = {
    "Object": "Object",
    "Material": "Material",
    "NodeTree": "NodeTree",
    "Collection": "Collection",
}


def _setup_factory_scene() -> None:
    """Create a minimal empty scene with correct unit settings (fallback when
    no _export_template.blend is available)."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    _apply_unit_settings()


def _apply_unit_settings() -> None:
    """Ensure scene units are Metric / mm / 0.001 scale."""
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 0.001
    scene.unit_settings.length_unit = 'MILLIMETERS'


def _append_asset(source: str, asset_name: str, asset_type: str) -> None:
    """Append *asset_name* of *asset_type* from *source* .blend."""
    dir_segment = _APPEND_DIRS.get(asset_type)
    if dir_segment is None:
        print(f"ERROR: Unknown asset type '{asset_type}'. "
              f"Expected one of: {list(_APPEND_DIRS.keys())}", file=sys.stderr)
        sys.exit(1)

    directory = os.path.join(source, dir_segment) + os.sep
    filepath = os.path.join(directory, asset_name)

    print(f"Appending '{asset_name}' from {directory}")
    bpy.ops.wm.append(
        filepath=filepath,
        directory=directory,
        filename=asset_name,
        link=False,
        autoselect=False,
        active_collection=True,
    )


def _cleanup_smuggled_assets(target_name: str) -> None:
    """Strip asset markings from every data block that is not the target.

    Data blocks whose ``asset_data`` is cleared but are still referenced
    as dependencies survive. Unreferenced blocks are cleaned by
    ``orphans_purge`` afterwards.
    """
    data_collections = [
        bpy.data.objects,
        bpy.data.materials,
        bpy.data.node_groups,
        bpy.data.collections,
        bpy.data.worlds,
        bpy.data.brushes,
    ]
    for collection in data_collections:
        for block in collection:
            if block.asset_data is not None and block.name != target_name:
                print(f"  Stripping asset marking from: {type(block).__name__} '{block.name}'")
                # Blender 5.0+ removed asset_data.clear(); use asset_clear() instead
                if hasattr(block, 'asset_clear'):
                    block.asset_clear()
                elif hasattr(block.asset_data, 'clear'):
                    block.asset_data.clear()
                else:
                    # Fallback: mark for removal by clearing the fake user
                    block.use_fake_user = False

    # Purge true orphans
    bpy.ops.outliner.orphans_purge(
        do_local_ids=True,
        do_linked_ids=True,
        do_recursive=True,
    )


def _extract_thumbnail(asset_name: str, output_dir: str) -> None:
    """Extract the asset preview image as icon_{FolderName}.png.

    Uses the folder name (from output_dir) for the icon filename,
    not the asset name, to match the pipeline convention.
    """
    import array as _array

    folder_name = os.path.basename(output_dir)

    # Find the marked asset
    for col in [bpy.data.objects, bpy.data.node_groups,
                bpy.data.materials, bpy.data.collections]:
        for item in col:
            if getattr(item, "asset_data", None) is None:
                continue
            if item.name != asset_name:
                continue

            preview = item.preview
            if not preview or preview.image_size[0] == 0:
                print(f"  No preview available for '{item.name}' — skipping thumbnail")
                return

            width, height = preview.image_size
            pixels = list(preview.image_pixels_float)
            if not pixels:
                print(f"  Empty preview pixels for '{item.name}' — skipping thumbnail")
                return

            # Convert float RGBA to byte array
            pixel_bytes = _array.array("B")
            for i in range(0, len(pixels), 4):
                r = max(0, min(255, int(pixels[i] * 255)))
                g = max(0, min(255, int(pixels[i + 1] * 255)))
                b = max(0, min(255, int(pixels[i + 2] * 255)))
                a = max(0, min(255, int(pixels[i + 3] * 255)))
                pixel_bytes.extend([r, g, b, a])

            thumb_path = os.path.join(output_dir, f"icon_{folder_name}.png")
            temp_img = bpy.data.images.new("_tmp_thumb", width=width, height=height, alpha=True)
            temp_img.pixels = [p / 255.0 for p in pixel_bytes]
            temp_img.filepath_raw = thumb_path
            temp_img.file_format = "PNG"
            temp_img.save()
            bpy.data.images.remove(temp_img)
            print(f"  Thumbnail saved: {thumb_path} ({width}x{height})")
            return

    print(f"  Asset '{asset_name}' not found for thumbnail extraction")


def main() -> None:
    args = _parse_args()

    # --- Factory fallback (no template loaded) ---
    if args.no_template:
        _setup_factory_scene()
    else:
        # Template is already open — ensure units are correct (safety net)
        _apply_unit_settings()

    # --- Append asset ---
    _append_asset(args.source, args.asset, args.asset_type)

    # --- Cleanup smuggled assets ---
    _cleanup_smuggled_assets(args.asset)

    # --- Save ---
    output_dir = os.path.dirname(args.output)
    os.makedirs(output_dir, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=args.output, compress=True)
    print(f"Saved to {args.output}")

    # --- Extract thumbnail ---
    _extract_thumbnail(args.asset, output_dir)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
