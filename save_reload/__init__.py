# SPDX-License-Identifier: GPL-3.0-or-later
"""Save & Reload — one-click iteration save + relaunch of this Blender instance.

Vendored into No3d Asset Developer as a feature subpackage. Its preferences are
folded into the host NO3D_AddonPreferences (Blender allows one AddonPreferences
per add-on); this package exposes only the operator, File-menu entry, and keymap.
macOS only.
"""

from . import save_op

_modules = (save_op,)


def register():
    for m in _modules:
        if hasattr(m, "register"):
            m.register()


def unregister():
    for m in reversed(_modules):
        if hasattr(m, "unregister"):
            m.unregister()
