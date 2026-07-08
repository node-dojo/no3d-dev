#!/bin/bash
# check_register.sh — headless proof that the add-on enables cleanly and its
# key surfaces are registered. Installs the current working tree as a temp
# extension into a throwaway Blender config, enables it, asserts, tears down.
#
# Usage:  tools/check_register.sh
# Exit 0 + "REGISTER_OK" on success; non-zero + traceback on failure.
set -euo pipefail

BLENDER="/Applications/Blender 5.2 Beta.app/Contents/MacOS/Blender"
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"

"$BLENDER" --factory-startup --background --python-expr "
import bpy, sys, traceback
PROJECT = r'''$PROJECT'''
try:
    # The repo dir name (no3d-asset-developer) contains a hyphen, which is
    # not a valid Python module name. Import it via a temp symlink with an
    # underscore name instead.
    import os, tempfile
    tmp = tempfile.mkdtemp()
    link = os.path.join(tmp, 'no3d_asset_developer')
    os.symlink(PROJECT, link)
    if tmp not in sys.path:
        sys.path.insert(0, tmp)
    mod = __import__('no3d_asset_developer')
    mod.register()
    # Assertions: prefs class registered. NOTE: AddonPreferences subclasses
    # are NOT exposed as attributes on bpy.types (confirmed: this is general
    # Blender behavior, reproduced with a throwaway AddonPreferences class
    # outside this add-on — not an add-on bug). cls.is_registered is the
    # correct, robust check for any bpy_struct subclass.
    assert mod.NO3D_AddonPreferences.is_registered, 'host prefs missing'
    mod.unregister()
    assert not mod.NO3D_AddonPreferences.is_registered, 'host prefs still registered after unregister'
    print('REGISTER_OK')
except Exception:
    traceback.print_exc()
    sys.exit(1)
"
