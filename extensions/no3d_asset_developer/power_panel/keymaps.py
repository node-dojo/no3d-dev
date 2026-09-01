"""Single keymap lifecycle for all Power Panel entry gestures."""

from . import pie, search


def register():
    search._register_keymap()
    pie._register_keymap()


def unregister():
    pie._unregister_keymap()
    search._unregister_keymap()


def groups():
    return (
        ("Power Panel Filter (3D View)", search._addon_keymaps),
        ("Power Panel Pie (3D View)", pie._addon_keymaps),
    )
