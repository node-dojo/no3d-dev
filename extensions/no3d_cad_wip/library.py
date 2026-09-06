"""Local-first Geometry Nodes definition lookup and WIP publication."""

from __future__ import annotations

import os

import bpy


LIB_BLEND = os.path.join(os.path.dirname(__file__), "assets", "no3d_nodes.blend")


def _local_group(names):
    for name in names:
        group = bpy.data.node_groups.get(name)
        if group is not None and group.bl_idname == "GeometryNodeTree":
            return group
    return None


def _append_group(blend_path, names):
    if not blend_path or not os.path.exists(blend_path):
        return None
    with bpy.data.libraries.load(blend_path, link=False) as (source, destination):
        selected = next((name for name in names if name in source.node_groups), None)
        if selected is None:
            return None
        destination.node_groups = [selected]
    return _local_group((selected,))


def registered_asset_blend(library_name, relative_path):
    libraries = bpy.context.preferences.filepaths.asset_libraries
    library = next((item for item in libraries if item.name == library_name), None)
    if library is None:
        return None
    return os.path.join(bpy.path.abspath(library.path), *relative_path)


def get_or_fetch_group(names, *, asset_library=None, asset_blend=None):
    if isinstance(names, str):
        names = (names,)
    group = _local_group(names)
    if group is not None:
        return group
    group = _append_group(LIB_BLEND, names)
    if group is not None:
        return group
    if asset_library and asset_blend:
        return _append_group(registered_asset_blend(asset_library, asset_blend), names)
    return None


def publish_group(group):
    """Publish one definition to the current single-group WIP library."""
    group.use_fake_user = True
    if not group.asset_data:
        group.asset_mark()
    os.makedirs(os.path.dirname(LIB_BLEND), exist_ok=True)
    bpy.data.libraries.write(LIB_BLEND, {group}, fake_user=True, compress=True)
