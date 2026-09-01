"""Blender regression test for the current-file Stowaway Inspector."""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import bpy


PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT, "extensions"))

from no3d_asset_developer import stowaway_inspector as inspector  # noqa: E402


bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.data.scenes.new("Scene")
bpy.context.window.scene = scene

root = bpy.data.objects.new("Root Asset", bpy.data.meshes.new("Root Mesh"))
helper = bpy.data.objects.new("Intentional Helper", bpy.data.meshes.new("Helper Mesh"))
stale = bpy.data.objects.new("Inactive Stowaway", bpy.data.meshes.new("Stale Mesh"))
unrelated = bpy.data.objects.new("Unrelated Scene Object", bpy.data.meshes.new("Unrelated Mesh"))
for obj in (root, helper, stale, unrelated):
    scene.collection.objects.link(obj)
root.asset_mark()

tree = bpy.data.node_groups.new("Inspector Test", "GeometryNodeTree")
tree.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
tree.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
group_in = tree.nodes.new("NodeGroupInput")
group_out = tree.nodes.new("NodeGroupOutput")
join = tree.nodes.new("GeometryNodeJoinGeometry")
live_info = tree.nodes.new("GeometryNodeObjectInfo")
live_info.name = "Live Helper Reference"
live_info.inputs["Object"].default_value = helper
stale_info = tree.nodes.new("GeometryNodeObjectInfo")
stale_info.name = "Inactive Stowaway Reference"
stale_info.inputs["Object"].default_value = stale
tree.links.new(group_in.outputs["Geometry"], join.inputs["Geometry"])
tree.links.new(live_info.outputs["Geometry"], join.inputs["Geometry"])
tree.links.new(join.outputs["Geometry"], group_out.inputs["Geometry"])

modifier = root.modifiers.new("GeometryNodes", "NODES")
modifier.node_group = tree

scan = inspector.scan_target(inspector.Target(root, "Active Object"))
rows = {row["name"]: row for row in scan["objects"]}
assert rows[helper.name]["status"] == "Live branch", rows
assert rows[stale.name]["status"] == "Inactive branch", rows
assert unrelated.name not in rows, rows
assert len(scan["asset_roots"]) == 1, scan["asset_roots"]

fake_context = SimpleNamespace(
    space_data=SimpleNamespace(type="VIEW_3D"),
    active_object=root,
    scene=scene,
)
preview = inspector._scene_clean_preview(fake_context)
assert preview is not None
assert helper in preview[2]
assert stale in preview[2], "Scene Clean must preserve even inactive dependencies"
assert unrelated in preview[3]

tree.nodes.remove(stale_info)
scan_after_manual_disconnect = inspector.scan_target(inspector.Target(root, "Active Object"))
assert stale not in scan_after_manual_disconnect["closure"]

print("STOWAWAY_INSPECTOR_OK")
