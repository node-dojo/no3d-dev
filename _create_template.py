"""
No3d Asset Developer — Template .blend generator.

Run this script ONCE in Blender to create ``_export_template.blend``.
The resulting file is bundled with the addon and used by the subprocess
export pipeline.

Usage:
    blender --background --python _create_template.py

The script saves ``_export_template.blend`` in the same directory as itself.
"""

import os
import sys

import bpy


def main():
    # Start from a completely empty scene
    bpy.ops.wm.read_factory_settings(use_empty=True)

    scene = bpy.context.scene

    # Unit settings: Metric, millimeters, 0.001 scale
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 0.001
    scene.unit_settings.length_unit = 'MILLIMETERS'

    # Color management: Standard / sRGB
    scene.view_settings.view_transform = 'Standard'
    try:
        scene.display_settings.display_device = 'sRGB'
    except TypeError:
        pass  # Some Blender builds use a different enum

    # Delete any default objects (use_empty=True should give us none, but be safe)
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    # Delete any default materials
    for mat in list(bpy.data.materials):
        bpy.data.materials.remove(mat, do_unlink=True)

    # Save
    output_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(output_dir, "_export_template.blend")

    bpy.ops.wm.save_as_mainfile(filepath=output_path, compress=True)
    print(f"Template saved to: {output_path}")


if __name__ == "__main__":
    main()
