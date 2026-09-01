import bpy

from . import operators, preferences, ui


def register():
    preferences.register()
    operators.register()
    ui.register()


def unregister():
    ui.unregister()
    operators.unregister()
    preferences.unregister()
