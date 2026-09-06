"""Focused Blender 5.2 acceptance for No3d CAD.wip Feature Tools."""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import bpy


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTENSIONS = os.path.join(ROOT, "extensions")
if EXTENSIONS not in sys.path:
    sys.path.insert(0, EXTENSIONS)

import no3d_cad_wip


def geometry_group(name, *, object_input=False):
    tree = bpy.data.node_groups.new(name, "GeometryNodeTree")
    tree.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    if object_input:
        tree.interface.new_socket(name="Seam tolerance", in_out="INPUT", socket_type="NodeSocketFloat")
        tree.interface.new_socket(name="Object", in_out="INPUT", socket_type="NodeSocketObject")
    tree.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    group_input = tree.nodes.new("NodeGroupInput")
    group_output = tree.nodes.new("NodeGroupOutput")
    tree.links.new(group_input.outputs["Geometry"], group_output.inputs["Geometry"])
    return tree


def mesh_object(name):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(
        [(-1, -2, -3), (1, -2, -3), (-1, 2, -3), (1, 2, -3),
         (-1, -2, 3), (1, -2, 3), (-1, 2, 3), (1, 2, 3)],
        [],
        [],
    )
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


no3d_cad_wip.register()
try:
    popup_calls = []
    popup_context = SimpleNamespace(
        window_manager=SimpleNamespace(invoke_search_popup=lambda operator: popup_calls.append(operator))
    )
    popup_operator = object()
    assert no3d_cad_wip.feature_tools.invoke_search_popup(popup_operator, popup_context) == {
        "RUNNING_MODAL"
    }
    assert popup_calls == [popup_operator]

    specs = no3d_cad_wip.feature_tools.registered_feature_tools()
    assert [spec.id for spec in specs] == [
        "generic", "split_with_plane",
    ]
    assert specs == (
        no3d_cad_wip.generic_ftool.FEATURE_TOOL_SPEC,
        no3d_cad_wip.split_with_plane.FEATURE_TOOL_SPEC,
    )
    search_items = no3d_cad_wip.feature_tools._tool_items(None, bpy.context)
    assert [item[0] for item in search_items] == ["generic", "split_with_plane"]
    assert no3d_cad_wip.feature_tools.NO3D_CAD_OT_feature_tool_search.bl_property == "feature_tool"
    assert no3d_cad_wip.generic_ftool.NO3D_CAD_OT_set_reference_feature.bl_property == "node_group"
    no3d_cad_wip._reload_package(no3d_cad_wip.__name__)
    assert [spec.id for spec in no3d_cad_wip.feature_tools.registered_feature_tools()] == [
        "generic", "split_with_plane",
    ]
    if bpy.context.window_manager.keyconfigs.addon is not None:
        assert len(no3d_cad_wip._addon_keymaps) == 4
        feature_keymap = no3d_cad_wip._addon_keymaps[0][1]
        assert feature_keymap.idname == "no3d_cad.feature_tool_search"
        assert feature_keymap.type == "F" and feature_keymap.shift
        line_keymap = no3d_cad_wip._addon_keymaps[1][1]
        feature_line_keymap = no3d_cad_wip._addon_keymaps[2][1]
        assert line_keymap.idname == "no3d_cad.add_mesh_line"
        assert line_keymap.type == "FOUR" and line_keymap.shift and not line_keymap.oskey
        assert feature_line_keymap.idname == "no3d_cad.add_mesh_line_feature"
        assert feature_line_keymap.type == "FOUR" and feature_line_keymap.shift and feature_line_keymap.oskey
        embed_keymap = no3d_cad_wip._addon_keymaps[3][1]
        assert embed_keymap.idname == "no3d_cad.embed_selected_ftools"
        assert embed_keymap.type == "F" and embed_keymap.shift and embed_keymap.oskey
        assert no3d_cad_wip.keymaps.SHORTCUTS[3].operator == embed_keymap.idname

    split_definition = geometry_group("Split with Plane [wip]", object_input=True)
    owner_tree = geometry_group("Owner Geometry")
    owner = mesh_object("Feature Owner")
    feature_collection = bpy.data.collections.new("Feature Test Collection")
    bpy.context.scene.collection.children.link(feature_collection)
    feature_collection.objects.link(owner)
    bpy.context.scene.collection.objects.unlink(owner)
    modifier = owner.modifiers.new("Geometry Nodes", "NODES")
    modifier.node_group = owner_tree
    owner.select_set(True)
    bpy.context.view_layer.objects.active = owner

    assert bpy.ops.no3d_cad.add_split_with_plane.poll()
    assert bpy.ops.no3d_cad.add_split_with_plane() == {"FINISHED"}

    planes = [obj for obj in bpy.data.objects if obj.get("no3d_feature_tool") == "no3d.split-with-plane"]
    assert len(planes) == 1
    plane = planes[0]
    assert plane.parent == owner
    assert plane.display_type == "WIRE"
    assert plane.get("no3d_feature_owner") == owner.name
    nodes = [node for node in owner_tree.nodes if node.bl_idname == "GeometryNodeGroup" and node.node_tree == split_definition]
    assert len(nodes) == 1
    feature_node = nodes[0]
    assert feature_node.inputs["Object"].default_value == plane
    assert feature_node.inputs["Geometry"].is_linked
    assert feature_node.outputs["Geometry"].is_linked
    pinned_context = SimpleNamespace(
        space_data=SimpleNamespace(
            type="NODE_EDITOR",
            tree_type="GeometryNodeTree",
            id=owner,
        ),
        active_object=plane,
    )
    assert no3d_cad_wip.contexts.object_from_context(pinned_context) == owner
    assert no3d_cad_wip.contexts.geometry_owner_from_context(pinned_context) == owner
    assert no3d_cad_wip.generic_ftool.NO3D_CAD_OT_add_generic_ftool.poll(pinned_context)
    assert no3d_cad_wip.split_with_plane.NO3D_CAD_OT_add_split_with_plane.poll(pinned_context)
    selectionless_context = SimpleNamespace(
        space_data=SimpleNamespace(
            type="NODE_EDITOR",
            tree_type="GeometryNodeTree",
            id=owner,
            edit_tree=owner_tree,
        ),
        active_object=None,
        scene=bpy.context.scene,
    )
    assert no3d_cad_wip.contexts.object_from_context(selectionless_context) == owner
    assert no3d_cad_wip.generic_ftool.NO3D_CAD_OT_add_generic_ftool.poll(selectionless_context)
    standalone_tree = geometry_group("Standalone F-Tool Authoring")
    ownerless_context = SimpleNamespace(
        space_data=SimpleNamespace(
            type="NODE_EDITOR",
            tree_type="GeometryNodeTree",
            id=None,
            edit_tree=standalone_tree,
        ),
        active_object=None,
        scene=bpy.context.scene,
        collection=feature_collection,
    )
    assert no3d_cad_wip.contexts.object_from_context(ownerless_context) is None
    assert no3d_cad_wip.generic_ftool.NO3D_CAD_OT_add_generic_ftool.poll(ownerless_context)
    ownerless_reference, _ownerless_modifier = no3d_cad_wip.generic_ftool._create_reference(
        None, "ownerless-test", ownerless_context,
    )
    assert ownerless_reference.parent is None
    assert ownerless_reference in feature_collection.objects.values()
    ownerless_mesh = ownerless_reference.data
    bpy.data.objects.remove(ownerless_reference, do_unlink=True)
    bpy.data.meshes.remove(ownerless_mesh)
    helper_context = SimpleNamespace(
        space_data=SimpleNamespace(type="VIEW_3D", tree_type=None),
        active_object=plane,
    )
    assert no3d_cad_wip.contexts.geometry_owner_from_context(helper_context) == owner
    button_context = SimpleNamespace(
        button_pointer=feature_node.inputs["Object"],
        button_prop=feature_node.inputs["Object"].bl_rna.properties["default_value"],
    )
    assert no3d_cad_wip.object_references.object_from_button_context(button_context) == plane

    plane_identity = plane.as_pointer()
    plane_mesh = plane.data
    plane_parent = plane.parent
    for collection in tuple(plane.users_collection):
        collection.objects.unlink(plane)
    assert plane.name not in bpy.context.scene.objects
    assert feature_node.inputs["Object"].default_value == plane
    assert bpy.ops.no3d_cad.relink_referenced_object(target_name=plane.name) == {"FINISHED"}
    assert plane.name in bpy.context.scene.objects
    assert plane.as_pointer() == plane_identity
    assert plane.data == plane_mesh
    assert plane.parent == plane_parent
    assert plane in feature_collection.objects.values()

    bpy.context.view_layer.objects.active = owner
    owner.select_set(True)
    plane.select_set(False)
    assert bpy.ops.no3d_cad.add_generic_ftool.poll()
    assert bpy.ops.no3d_cad.add_generic_ftool() == {"FINISHED"}
    generic_refs = [obj for obj in bpy.data.objects if obj.get("no3d_feature_tool") == "no3d.generic-ftool"]
    assert len(generic_refs) == 1
    generic_ref = generic_refs[0]
    assert generic_ref.parent == owner
    instances = no3d_cad_wip.generic_ftool.instances_for_object(generic_ref)
    assert len(instances) == 1
    _, found_owner, found_ref, reference_modifier, embed_node, object_input = instances[0]
    assert found_owner == owner
    assert found_ref == generic_ref
    assert object_input.default_value == generic_ref
    default_embed = embed_node.node_tree
    assert "Geometry" not in embed_node.inputs
    object_info_nodes = [
        node for node in default_embed.nodes if node.bl_idname == "GeometryNodeObjectInfo"
    ]
    assert len(object_info_nodes) == 1
    object_info = object_info_nodes[0]
    assert any(
        link.from_socket == default_embed.nodes.get("Group Input").outputs["Object"]
        and link.to_socket == object_info.inputs["Object"]
        for link in default_embed.links
    )
    assert any(
        link.from_socket == object_info.outputs["Geometry"]
        and link.to_socket == default_embed.nodes.get("Group Output").inputs["Geometry"]
        for link in default_embed.links
    )
    owner_output = next(node for node in owner_tree.nodes if node.bl_idname == "NodeGroupOutput")
    assert owner_output.inputs["Geometry"].links[0].from_node == embed_node
    evaluated_owner = owner.evaluated_get(bpy.context.evaluated_depsgraph_get())
    assert len(evaluated_owner.data.vertices) == 1
    alternate_reference = geometry_group("Alternate Reference")
    alternate_embed = geometry_group("Alternate Embed", object_input=True)
    instance_id = generic_ref["no3d_ftool_instance_id"]
    assert bpy.ops.no3d_cad.set_reference_feature(
        instance_id=instance_id,
        node_group=alternate_reference.name,
    ) == {"FINISHED"}
    assert bpy.ops.no3d_cad.set_embed_feature(
        instance_id=instance_id,
        node_group=alternate_embed.name,
    ) == {"FINISHED"}
    assert reference_modifier.node_group == alternate_reference
    assert embed_node.node_tree == alternate_embed
    assert embed_node.inputs["Object"].default_value == generic_ref

    area = bpy.context.screen.areas[0]
    previous_area_type = area.type
    try:
        area.type = "NODE_EDITOR"
        space = area.spaces.active
        space.tree_type = "GeometryNodeTree"
        if hasattr(space, "geometry_nodes_type"):
            space.geometry_nodes_type = "MODIFIER"
        space.pin = False
        space.cursor_location = (321.0, -123.0)
        region = next(item for item in area.regions if item.type == "WINDOW")
        links_before = {
            (
                link.from_node.as_pointer(), link.from_socket.identifier,
                link.to_node.as_pointer(), link.to_socket.identifier,
            )
            for link in owner_tree.links
        }
        generic_nodes_before = {
            node.as_pointer() for node in owner_tree.nodes if node.get("no3d_ftool_instance_id")
        }
        split_nodes_before = {
            node.as_pointer()
            for node in owner_tree.nodes
            if node.bl_idname == "GeometryNodeGroup" and node.node_tree == split_definition
        }
        with bpy.context.temp_override(area=area, region=region):
            assert bpy.ops.no3d_cad.add_generic_ftool.poll()
            assert bpy.ops.no3d_cad.add_generic_ftool() == {"FINISHED"}
            assert bpy.ops.no3d_cad.add_split_with_plane.poll()
            assert bpy.ops.no3d_cad.add_split_with_plane() == {"FINISHED"}
        new_generic_node = next(
            node
            for node in owner_tree.nodes
            if node.get("no3d_ftool_instance_id") and node.as_pointer() not in generic_nodes_before
        )
        new_split_node = next(
            node
            for node in owner_tree.nodes
            if node.bl_idname == "GeometryNodeGroup"
            and node.node_tree == split_definition
            and node.as_pointer() not in split_nodes_before
        )
        assert tuple(new_generic_node.location) == (321.0, -123.0)
        assert tuple(new_split_node.location) == (321.0, -123.0)
        assert not new_generic_node.inputs["Object"].is_linked
        assert new_generic_node.inputs["Object"].default_value is not None
        assert not new_generic_node.outputs["Geometry"].is_linked
        assert not new_split_node.inputs["Geometry"].is_linked
        assert new_split_node.inputs["Object"].default_value is not None
        assert not new_split_node.outputs["Geometry"].is_linked
        assert {
            (
                link.from_node.as_pointer(), link.from_socket.identifier,
                link.to_node.as_pointer(), link.to_socket.identifier,
            )
            for link in owner_tree.links
        } == links_before
        assert any(
            instance[4] == new_generic_node
            for instance in no3d_cad_wip.generic_ftool.instances_for_object(owner)
        )
    finally:
        area.type = previous_area_type

    area = bpy.context.screen.areas[0]
    previous_area_type = area.type
    try:
        area.type = "VIEW_3D"
        region = next(item for item in area.regions if item.type == "WINDOW")
        bpy.context.scene.cursor.location = (4.0, 5.0, 6.0)
        with bpy.context.temp_override(area=area, region=region):
            assert bpy.ops.no3d_cad.add_mesh_line.poll()
            assert bpy.ops.no3d_cad.add_mesh_line(begin_placement=False) == {"FINISHED"}
        mesh_line = bpy.context.active_object
        assert tuple(mesh_line.location) == (4.0, 5.0, 6.0)
        assert len(mesh_line.data.vertices) == 2
        assert len(mesh_line.data.edges) == 1

        mesh_line.select_set(False)
        blank_target = mesh_object("Blank Feature Target")
        assert len(blank_target.modifiers) == 0
        blank_target.select_set(True)
        bpy.context.view_layer.objects.active = blank_target
        with bpy.context.temp_override(area=area, region=region):
            assert bpy.ops.no3d_cad.add_mesh_line_feature.poll()
            assert bpy.ops.no3d_cad.add_mesh_line_feature(begin_placement=False) == {"FINISHED"}
        feature_line = bpy.context.active_object
        assert feature_line.parent == blank_target
        assert tuple(feature_line.matrix_world.translation) == (4.0, 5.0, 6.0)
        assert len(feature_line.data.vertices) == 2
        assert len(feature_line.data.edges) == 1
        assert feature_line.modifiers[0].node_group.name == "F-Tool Reference"
        assert len(blank_target.modifiers) == 1
        blank_modifier = blank_target.modifiers[0]
        assert blank_modifier.type == "NODES"
        blank_tree = blank_modifier.node_group
        group_input = next(node for node in blank_tree.nodes if node.bl_idname == "NodeGroupInput")
        group_output = next(node for node in blank_tree.nodes if node.bl_idname == "NodeGroupOutput")
        assert any(
            link.from_node == group_input and link.to_node == group_output
            for link in blank_tree.links
        )
        feature_line_node = next(
            node for node in blank_tree.nodes
            if node.get("no3d_feature_tool") == "no3d.mesh-line"
        )
        assert feature_line_node.inputs["Object"].default_value == feature_line
        assert not feature_line_node.outputs["Geometry"].is_linked

        feature_line.select_set(False)
        bpy.context.view_layer.objects.active = None
        with bpy.context.temp_override(area=area, region=region):
            assert bpy.ops.no3d_cad.add_mesh_line_feature.poll()
            assert no3d_cad_wip.mesh_line._selected_feature_owner(bpy.context) is None

        single_tree = geometry_group("Single Embed Owner Geometry")
        single_owner = mesh_object("Single Embed Owner")
        single_modifier = single_owner.modifiers.new("Geometry Nodes", "NODES")
        single_modifier.node_group = single_tree
        single_feature = mesh_object("Single Existing Feature")
        single_feature.location = (7.0, 8.0, 9.0)
        for obj in tuple(bpy.context.selected_objects):
            obj.select_set(False)
        single_owner.select_set(True)
        single_feature.select_set(True)
        bpy.context.view_layer.objects.active = single_owner
        single_links_before = {
            (link.from_node.name, link.from_socket.identifier, link.to_node.name, link.to_socket.identifier)
            for link in single_tree.links
        }
        with bpy.context.temp_override(area=area, region=region):
            assert bpy.ops.no3d_cad.embed_single_ftool.poll()
            assert bpy.ops.no3d_cad.embed_single_ftool(presentation="WIRE") == {"FINISHED"}
        assert single_feature.parent == single_owner
        assert tuple(single_feature.matrix_world.translation) == (7.0, 8.0, 9.0)
        assert single_feature.display_type == "WIRE"
        single_embed = next(
            node for node in single_tree.nodes
            if node.get("no3d_feature_tool") == "no3d.embed-existing"
        )
        assert single_embed.node_tree.name == "F-Tool Embed"
        assert single_embed.inputs["Object"].default_value == single_feature
        assert not single_embed.outputs["Geometry"].is_linked
        assert {
            (link.from_node.name, link.from_socket.identifier, link.to_node.name, link.to_socket.identifier)
            for link in single_tree.links
        } == single_links_before
        assert all(tuple(single_embed.location) != tuple(node.location) for node in single_tree.nodes if node != single_embed)
        assert not any(
            group.get("no3d_ftool_role") == "batch-definition"
            for group in bpy.data.node_groups
        )

        batch_owner = mesh_object("Batch Embed Owner")
        batch_features = [mesh_object(f"Batch Existing Feature {index}") for index in range(3)]
        for index, obj in enumerate(batch_features):
            obj.location = (float(index + 1), float(index + 2), float(index + 3))
        for obj in tuple(bpy.context.selected_objects):
            obj.select_set(False)
        batch_owner.select_set(True)
        for obj in batch_features:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = batch_owner
        local_view_filtered_context = SimpleNamespace(
            active_object=batch_owner,
            selected_objects=[batch_owner],
            view_layer=bpy.context.view_layer,
        )
        resolved_owner, resolved_features = no3d_cad_wip.batch_embed.selected_owner_and_features(
            local_view_filtered_context
        )
        assert resolved_owner == batch_owner
        assert resolved_features == batch_features
        with bpy.context.temp_override(area=area, region=region):
            assert bpy.ops.no3d_cad.embed_batch_ftools.poll()
            assert bpy.ops.no3d_cad.embed_batch_ftools(presentation="HIDDEN") == {"FINISHED"}
        assert len(batch_owner.modifiers) == 1
        batch_tree = batch_owner.modifiers[0].node_group
        batch_outer = next(
            node for node in batch_tree.nodes
            if node.get("no3d_ftool_role") == "batch-embed"
        )
        batch_group = batch_outer.node_tree
        assert batch_group.get("no3d_ftool_role") == "batch-definition"
        assert len([item for item in batch_group.interface.items_tree if item.in_out == "INPUT"]) == 3
        batch_embeds = [
            node for node in batch_group.nodes
            if node.get("no3d_ftool_role") == "embed"
        ]
        assert len(batch_embeds) == 3
        assert all(node.outputs["Geometry"].is_linked for node in batch_embeds)
        assert [batch_outer.inputs[index].default_value for index in range(3)] == batch_features
        assert not batch_outer.outputs["Geometry"].is_linked
        batch_output = next(node for node in batch_tree.nodes if node.bl_idname == "NodeGroupOutput")
        assert batch_output.inputs["Geometry"].links[0].from_node.bl_idname == "NodeGroupInput"
        assert all(tuple(batch_outer.location) != tuple(node.location) for node in batch_tree.nodes if node != batch_outer)
        for index, obj in enumerate(batch_features):
            assert obj.parent == batch_owner
            assert tuple(obj.matrix_world.translation) == (
                float(index + 1), float(index + 2), float(index + 3),
            )
            assert obj.hide_get()

        area.type = "NODE_EDITOR"
        node_space = area.spaces.active
        node_space.tree_type = "GeometryNodeTree"
        if hasattr(node_space, "geometry_nodes_type"):
            node_space.geometry_nodes_type = "MODIFIER"
        node_space.pin = False
        region = next(item for item in area.regions if item.type == "WINDOW")
        for node in batch_tree.nodes:
            node.select = node == batch_outer
        with bpy.context.temp_override(area=area, region=region):
            assert bpy.ops.no3d_cad.promote_object_inputs.poll()
            assert bpy.ops.no3d_cad.promote_object_inputs() == {"FINISHED"}
        root_object_inputs = [
            item for item in batch_tree.interface.items_tree
            if item.item_type == "SOCKET"
            and item.in_out == "INPUT"
            and item.socket_type == "NodeSocketObject"
        ]
        assert len(root_object_inputs) == 3
        assert [item.default_value for item in root_object_inputs] == batch_features
        assert [
            getattr(batch_owner.modifiers[0].properties.inputs, item.identifier).value
            for item in root_object_inputs
        ] == batch_features
        assert all(socket.is_linked for socket in batch_outer.inputs if socket.type == "OBJECT")
        assert all(
            socket.links[0].from_node.bl_idname == "NodeGroupInput"
            for socket in batch_outer.inputs if socket.type == "OBJECT"
        )

        area.type = "VIEW_3D"
        region = next(item for item in area.regions if item.type == "WINDOW")
        toggle_owner = mesh_object("Toggle Embed Owner")
        toggle_features = [mesh_object(f"Toggle Feature {index}") for index in range(2)]
        for obj in tuple(bpy.context.selected_objects):
            obj.select_set(False)
        toggle_owner.select_set(True)
        for obj in toggle_features:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = toggle_owner
        with bpy.context.temp_override(area=area, region=region):
            assert bpy.ops.no3d_cad.embed_selected_ftools(
                presentation="UNCHANGED",
                expose_objects_in_modifier=True,
            ) == {"FINISHED"}
        toggle_tree = toggle_owner.modifiers[0].node_group
        toggle_outer = next(
            node for node in toggle_tree.nodes
            if node.get("no3d_ftool_role") == "batch-embed"
        )
        toggle_inputs = [
            item for item in toggle_tree.interface.items_tree
            if item.item_type == "SOCKET"
            and item.in_out == "INPUT"
            and item.socket_type == "NodeSocketObject"
        ]
        assert [item.default_value for item in toggle_inputs] == toggle_features
        assert [
            getattr(toggle_owner.modifiers[0].properties.inputs, item.identifier).value
            for item in toggle_inputs
        ] == toggle_features
        assert all(socket.is_linked for socket in toggle_outer.inputs if socket.type == "OBJECT")
    finally:
        area.type = previous_area_type

    print("NO3D_CAD_FEATURE_TOOLS_OK")
finally:
    no3d_cad_wip.unregister()
    assert no3d_cad_wip.feature_tools.registered_feature_tools() == ()
