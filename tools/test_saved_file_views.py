"""Blender factory-startup checks for No3d File Browser Saved Views."""

import sys
from unittest.mock import patch
from pathlib import Path

import bpy
from bpy.props import BoolProperty, CollectionProperty
from bpy.types import PropertyGroup


extensions_dir = Path(__file__).resolve().parents[1] / "extensions"
sys.path.insert(0, str(extensions_dir))

from no3d_asset_developer import saved_file_views as module


class NO3D_TestSavedViewsOwner(PropertyGroup):
    views: CollectionProperty(type=module.NO3D_FileBrowserSavedView)
    initialized: BoolProperty(default=False)


module.register_types()
bpy.utils.register_class(NO3D_TestSavedViewsOwner)
bpy.types.Scene.no3d_test_saved_views = bpy.props.PointerProperty(
    type=NO3D_TestSavedViewsOwner
)

try:
    owner = bpy.context.scene.no3d_test_saved_views

    class PreferencesAdapter:
        @property
        def saved_file_views(self):
            return owner.views

        @property
        def saved_file_views_initialized(self):
            return owner.initialized

        @saved_file_views_initialized.setter
        def saved_file_views_initialized(self, value):
            owner.initialized = value

    prefs = PreferencesAdapter()
    with patch.object(module.os.path, "isdir", return_value=True):
        module.seed_default_views(prefs)
    assert len(owner.views) == 2

    well, birth = owner.views
    assert well.name == "Well Play"
    assert well.directory == module.WELL_PLAY_PATH
    assert well.display_type == 'LIST_VERTICAL'
    assert well.recursion_level == 'ALL_2'
    assert well.show_folders and well.show_blend
    assert not well.show_images and not well.show_movies

    assert birth.name == "Birth Graphics"
    assert birth.directory == module.BIRTH_GRAPHICS_PATH
    assert birth.display_type == 'THUMBNAIL'
    assert birth.display_size == 192
    assert birth.recursion_level == 'NONE'
    assert not birth.show_folders and not birth.show_blend
    assert birth.show_images and birth.show_movies

    class FakeParams:
        use_filter = False
        filter_search = "stale query"
        filter_glob = "*.txt"
        use_filter_folder = True
        use_filter_blender = True
        use_filter_backup = True
        use_filter_image = False
        use_filter_movie = False
        use_filter_script = True
        use_filter_font = True
        use_filter_sound = True
        use_filter_text = True
        use_filter_volume = True
        recursion_level = 'ALL_3'
        display_type = 'LIST_HORIZONTAL'
        display_size = 32

    params = FakeParams()
    module._apply_settings(params, birth)
    assert params.use_filter
    assert params.filter_search == "" and params.filter_glob == ""
    assert not params.use_filter_folder and not params.use_filter_blender
    assert params.use_filter_image and params.use_filter_movie
    assert not any(getattr(params, name) for name in module.FILTER_PROPERTIES if name not in {
        "use_filter_image", "use_filter_movie",
    })
    assert params.recursion_level == 'NONE'
    assert params.display_type == 'THUMBNAIL' and params.display_size == 192

    module.seed_default_views(prefs)
    assert len(owner.views) == 2
    assert module._unique_name(owner.views, "Well Play") == "Well Play 2"

    owner.views.clear()
    owner.initialized = False
    with patch.object(module.os.path, "isdir", return_value=False):
        module.seed_default_views(prefs)
    assert len(owner.views) == 0, "Fresh machines must not receive nonexistent bookmarks"

    module.register()
    try:
        assert module.NO3D_PT_file_browser_saved_views.is_registered
        cycle_items = [
            item for _keymap, item in module._addon_keymaps
            if item.idname == "no3d.cycle_file_browser_saved_view"
        ]
        assert len(cycle_items) == 2
        assert {item.type for item in cycle_items} == {'LEFT_BRACKET', 'RIGHT_BRACKET'}
    finally:
        module.unregister()
finally:
    del bpy.types.Scene.no3d_test_saved_views
    bpy.utils.unregister_class(NO3D_TestSavedViewsOwner)
    module.unregister_types()

print("SAVED_FILE_VIEWS_OK")
