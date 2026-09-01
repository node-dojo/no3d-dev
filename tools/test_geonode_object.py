"""Blender factory-startup smoke test for the GeoNode object command."""

import importlib.util
from pathlib import Path

import bpy


module_path = (
    Path(__file__).resolve().parents[1]
    / "extensions"
    / "no3d_asset_developer"
    / "geonode_object.py"
)
spec = importlib.util.spec_from_file_location("no3d_geonode_object_test", module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

module.register()
try:
    bpy.context.scene.cursor.location = (1.0, 2.0, 3.0)
    result = bpy.ops.mesh.no3d_add_geonode_object()
    assert result == {"FINISHED"}

    obj = bpy.context.active_object
    assert obj.name == "GeoNode_obj"
    assert tuple(obj.location) == (1.0, 2.0, 3.0)
    assert len(obj.data.vertices) == 1
    assert len(obj.modifiers) == 1

    modifier = obj.modifiers[0]
    assert modifier.type == "NODES"
    group = modifier.node_group
    assert group is not None
    assert len(group.nodes) == 2
    assert len(group.links) == 1

    bpy.ops.mesh.no3d_add_geonode_object()
    assert bpy.context.active_object.name == "GeoNode_obj.001"
finally:
    module.unregister()

print("GEONODE_OBJECT_OK")
