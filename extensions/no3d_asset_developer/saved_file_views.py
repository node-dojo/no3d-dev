"""Named File Browser locations with per-location display and filter state."""

from __future__ import annotations

import os

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup, UIList


WELL_PLAY_PATH = (
    "/Users/joebowers/Library/CloudStorage/Dropbox/Caveman Creative/"
    "THE WELL_Digital Assets/THE WELL_play files"
)
BIRTH_GRAPHICS_PATH = os.path.join(WELL_PLAY_PATH, "BIRTH_ GRAPHICS")

FILTER_PROPERTIES = (
    "use_filter_blender",
    "use_filter_backup",
    "use_filter_image",
    "use_filter_movie",
    "use_filter_script",
    "use_filter_font",
    "use_filter_sound",
    "use_filter_text",
    "use_filter_volume",
)


class NO3D_FileBrowserSavedView(PropertyGroup):
    name: StringProperty(name="Name", default="Saved View")
    directory: StringProperty(name="Folder", subtype='DIR_PATH')
    display_type: EnumProperty(
        name="Display",
        items=(
            ('LIST_VERTICAL', "Vertical List", "Compact vertical list"),
            ('LIST_HORIZONTAL', "Detailed List", "Horizontal detailed list"),
            ('THUMBNAIL', "Thumbnails", "Thumbnail grid"),
        ),
        default='LIST_VERTICAL',
    )
    recursion_level: EnumProperty(
        name="Recursions",
        items=(
            ('NONE', "None", "Only this folder"),
            ('ALL_1', "One Level", "Include one subfolder level"),
            ('ALL_2', "Two Levels", "Include two subfolder levels"),
            ('ALL_3', "Three Levels", "Include three subfolder levels"),
        ),
        default='NONE',
    )
    display_size: IntProperty(name="Thumbnail Size", default=192, min=16, max=256)
    show_folders: BoolProperty(name="Folders", default=True)
    show_blend: BoolProperty(name=".blend", default=True)
    show_images: BoolProperty(name="Images", default=False)
    show_movies: BoolProperty(name="Movies", default=False)


def _preferences(context):
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def _file_params(context):
    space = getattr(context, "space_data", None)
    if not space or space.type != 'FILE_BROWSER' or space.browse_mode != 'FILES':
        return None
    return space.params


def _directory_text(value) -> str:
    if isinstance(value, bytes):
        return os.fsdecode(value)
    return str(value or "")


def _unique_name(views, proposed: str) -> str:
    base = proposed or "Saved View"
    existing = {view.name for view in views}
    if base not in existing:
        return base
    suffix = 2
    while f"{base} {suffix}" in existing:
        suffix += 1
    return f"{base} {suffix}"


def _capture(view, params):
    directory = _directory_text(params.directory).rstrip(os.sep)
    view.directory = directory
    view.display_type = params.display_type
    view.recursion_level = params.recursion_level
    view.display_size = params.display_size
    view.show_folders = params.use_filter_folder
    view.show_blend = params.use_filter_blender
    view.show_images = params.use_filter_image
    view.show_movies = params.use_filter_movie


def _apply(context, view):
    params = _file_params(context)
    if params is None:
        raise RuntimeError("Saved Views only work in a regular File Browser")
    directory = bpy.path.abspath(view.directory)
    if not os.path.isdir(directory):
        raise RuntimeError(f"Folder does not exist: {directory}")

    bpy.ops.file.select_bookmark(dir=directory)
    params = context.space_data.params
    _apply_settings(params, view)
    bpy.ops.file.refresh()


def _apply_settings(params, view):
    """Apply a saved presentation to FileSelectParams after navigation."""
    params.use_filter = True
    params.filter_search = ""
    params.filter_glob = ""
    params.use_filter_folder = view.show_folders
    for prop_name in FILTER_PROPERTIES:
        setattr(params, prop_name, False)
    params.use_filter_blender = view.show_blend
    params.use_filter_image = view.show_images
    params.use_filter_movie = view.show_movies
    params.recursion_level = view.recursion_level
    params.display_type = view.display_type
    if view.display_type == 'THUMBNAIL':
        params.display_size = view.display_size


def seed_default_views(preferences):
    if preferences.saved_file_views_initialized:
        return
    preferences.saved_file_views_initialized = True

    if os.path.isdir(WELL_PLAY_PATH):
        well = preferences.saved_file_views.add()
        well.name = "Well Play"
        well.directory = WELL_PLAY_PATH
        well.display_type = 'LIST_VERTICAL'
        well.recursion_level = 'ALL_2'
        well.show_folders = True
        well.show_blend = True

    if os.path.isdir(BIRTH_GRAPHICS_PATH):
        birth = preferences.saved_file_views.add()
        birth.name = "Birth Graphics"
        birth.directory = BIRTH_GRAPHICS_PATH
        birth.display_type = 'THUMBNAIL'
        birth.recursion_level = 'NONE'
        birth.display_size = 192
        birth.show_folders = False
        birth.show_blend = False
        birth.show_images = True
        birth.show_movies = True


def _seed_defaults_timer():
    addon = bpy.context.preferences.addons.get(__package__)
    if addon:
        seed_default_views(addon.preferences)
    return None


class NO3D_UL_file_browser_saved_views(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "name", text="", emboss=False, icon='BOOKMARKS')
        op = row.operator("no3d.apply_file_browser_saved_view", text="", icon='FORWARD')
        op.index = index


class NO3D_OT_apply_file_browser_saved_view(Operator):
    bl_idname = "no3d.apply_file_browser_saved_view"
    bl_label = "Open Saved File View"
    bl_description = "Open this folder and apply its saved File Browser settings"

    index: IntProperty(options={'HIDDEN', 'SKIP_SAVE'}, default=-1)

    @classmethod
    def poll(cls, context):
        return _file_params(context) is not None

    def execute(self, context):
        prefs = _preferences(context)
        if prefs is None or not prefs.saved_file_views:
            return {'CANCELLED'}
        index = self.index if self.index >= 0 else prefs.saved_file_views_index
        if not 0 <= index < len(prefs.saved_file_views):
            return {'CANCELLED'}
        try:
            _apply(context, prefs.saved_file_views[index])
        except RuntimeError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        prefs.saved_file_views_index = index
        return {'FINISHED'}


class NO3D_OT_cycle_file_browser_saved_view(Operator):
    bl_idname = "no3d.cycle_file_browser_saved_view"
    bl_label = "Cycle Saved File View"
    bl_description = "Move to the previous or next No3d Saved View"

    direction: IntProperty(default=1, options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        prefs = _preferences(context)
        return _file_params(context) is not None and bool(prefs and prefs.saved_file_views)

    def execute(self, context):
        prefs = _preferences(context)
        count = len(prefs.saved_file_views)
        prefs.saved_file_views_index = (prefs.saved_file_views_index + self.direction) % count
        try:
            _apply(context, prefs.saved_file_views[prefs.saved_file_views_index])
        except RuntimeError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class NO3D_OT_capture_file_browser_saved_view(Operator):
    bl_idname = "no3d.capture_file_browser_saved_view"
    bl_label = "Save Current File View"
    bl_description = "Save the current folder, filters, recursion, and display without prompting"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _file_params(context) is not None

    def execute(self, context):
        prefs = _preferences(context)
        params = _file_params(context)
        directory = _directory_text(params.directory).rstrip(os.sep)
        proposed = os.path.basename(directory) or "Saved View"
        view = prefs.saved_file_views.add()
        existing_views = [
            prefs.saved_file_views[index]
            for index in range(len(prefs.saved_file_views) - 1)
        ]
        view.name = _unique_name(existing_views, proposed)
        _capture(view, params)
        prefs.saved_file_views_index = len(prefs.saved_file_views) - 1
        return {'FINISHED'}


class NO3D_OT_remove_file_browser_saved_view(Operator):
    bl_idname = "no3d.remove_file_browser_saved_view"
    bl_label = "Remove Saved File View"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        prefs = _preferences(context)
        index = prefs.saved_file_views_index
        if 0 <= index < len(prefs.saved_file_views):
            prefs.saved_file_views.remove(index)
            prefs.saved_file_views_index = min(index, len(prefs.saved_file_views) - 1)
        return {'FINISHED'}


class NO3D_OT_move_file_browser_saved_view(Operator):
    bl_idname = "no3d.move_file_browser_saved_view"
    bl_label = "Move Saved File View"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(items=(('UP', "Up", ""), ('DOWN', "Down", "")))

    def execute(self, context):
        prefs = _preferences(context)
        source = prefs.saved_file_views_index
        target = source + (-1 if self.direction == 'UP' else 1)
        if 0 <= source < len(prefs.saved_file_views) and 0 <= target < len(prefs.saved_file_views):
            prefs.saved_file_views.move(source, target)
            prefs.saved_file_views_index = target
        return {'FINISHED'}


class NO3D_PT_file_browser_saved_views(Panel):
    bl_label = "NO3D Saved Views"
    bl_idname = "NO3D_PT_file_browser_saved_views"
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOLS'
    bl_category = "Bookmarks"
    bl_order = 5

    @classmethod
    def poll(cls, context):
        space = getattr(context, "space_data", None)
        return bool(
            _file_params(context) is not None
            and space.active_operator is None
        )

    def draw(self, context):
        layout = self.layout
        prefs = _preferences(context)
        row = layout.row()
        row.template_list(
            "NO3D_UL_file_browser_saved_views", "", prefs,
            "saved_file_views", prefs, "saved_file_views_index", rows=3,
        )
        col = row.column(align=True)
        col.operator("no3d.capture_file_browser_saved_view", text="", icon='ADD')
        col.operator("no3d.remove_file_browser_saved_view", text="", icon='REMOVE')
        col.separator()
        col.operator("no3d.move_file_browser_saved_view", text="", icon='TRIA_UP').direction = 'UP'
        col.operator("no3d.move_file_browser_saved_view", text="", icon='TRIA_DOWN').direction = 'DOWN'

        nav = layout.row(align=True)
        nav.operator("no3d.cycle_file_browser_saved_view", text="Previous", icon='BACK').direction = -1
        nav.operator("no3d.cycle_file_browser_saved_view", text="Next", icon='FORWARD').direction = 1

        index = prefs.saved_file_views_index
        if not 0 <= index < len(prefs.saved_file_views):
            return
        view = prefs.saved_file_views[index]
        box = layout.box()
        box.prop(view, "directory", text="")
        box.prop(view, "display_type", text="")
        box.prop(view, "recursion_level", text="")
        if view.display_type == 'THUMBNAIL':
            box.prop(view, "display_size", slider=True)
        grid = box.grid_flow(columns=2, even_columns=True, align=True)
        grid.prop(view, "show_folders")
        grid.prop(view, "show_blend")
        grid.prop(view, "show_images")
        grid.prop(view, "show_movies")


_classes = (
    NO3D_UL_file_browser_saved_views,
    NO3D_OT_apply_file_browser_saved_view,
    NO3D_OT_cycle_file_browser_saved_view,
    NO3D_OT_capture_file_browser_saved_view,
    NO3D_OT_remove_file_browser_saved_view,
    NO3D_OT_move_file_browser_saved_view,
    NO3D_PT_file_browser_saved_views,
)

_addon_keymaps = []


def register_types():
    bpy.utils.register_class(NO3D_FileBrowserSavedView)


def unregister_types():
    bpy.utils.unregister_class(NO3D_FileBrowserSavedView)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig is not None:
        keymap = keyconfig.keymaps.new(name="File Browser", space_type='FILE_BROWSER')
        previous = keymap.keymap_items.new(
            "no3d.cycle_file_browser_saved_view", 'LEFT_BRACKET', 'PRESS', shift=True,
        )
        previous.properties.direction = -1
        _addon_keymaps.append((keymap, previous))
        next_item = keymap.keymap_items.new(
            "no3d.cycle_file_browser_saved_view", 'RIGHT_BRACKET', 'PRESS', shift=True,
        )
        next_item.properties.direction = 1
        _addon_keymaps.append((keymap, next_item))
    bpy.app.timers.register(_seed_defaults_timer, first_interval=0.0)


def unregister():
    if bpy.app.timers.is_registered(_seed_defaults_timer):
        bpy.app.timers.unregister(_seed_defaults_timer)
    for keymap, item in _addon_keymaps:
        try:
            keymap.keymap_items.remove(item)
        except Exception:
            pass
    _addon_keymaps.clear()
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
