"""Factory-startup regression probe for embed staging helpers."""

import bpy

from no3d_asset_developer import embed_staging


tree = bpy.data.node_groups.new("Embed Staging Test", 'GeometryNodeTree')
tree.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
output = tree.nodes.new('NodeGroupOutput')
cube = tree.nodes.new('GeometryNodeMeshCube')
tree.links.new(cube.outputs["Mesh"], output.inputs["Geometry"])

parent = bpy.data.node_groups.new("Embed Parent Test", 'GeometryNodeTree')
stage = parent.nodes.new('GeometryNodeGroup')
stage.node_tree = tree
store, reader = embed_staging.finish_staged_group(stage, "no3d_embed_test_mesh")

assert stage.inputs["Embed Name"].default_value == "no3d_embed_test_mesh"
assert store.bl_idname == 'GeometryNodeStoreNamedAttribute'
assert store.domain == 'POINT'
assert store.data_type == 'BOOLEAN'
assert reader.node_tree.name == embed_staging.READER_GROUP_NAME
assert reader.inputs["Attribute Name"].default_value == "no3d_embed_test_mesh"
sockets = [item for item in reader.node_tree.interface.items_tree if item.item_type == 'SOCKET']
assert [item.name for item in sockets if item.in_out == 'INPUT'] == [
    "Geometry", "Attribute Name"
]
assert [item.name for item in sockets if item.in_out == 'OUTPUT'] == [
    "Component", "Remainder", "Selection"
]
assert embed_staging._identifier("Lighter Head.004") == "no3d_embed_lighter_head_004"

source_mesh = bpy.data.meshes.new("Circle.033")
source_object = bpy.data.objects.new("lighter head", source_mesh)
object_info = parent.nodes.new('GeometryNodeObjectInfo')
object_info.inputs["Object"].default_value = source_object
assert embed_staging._object_names([object_info]) == ["lighter head"]

print("EMBED_STAGING_OK")
