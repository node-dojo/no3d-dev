"""Expose assigned Object inputs through group interfaces without losing values."""

from __future__ import annotations

import bpy
from bpy.types import Operator

from . import ids


def _interface_input(tree, identifier):
    return next(
        (
            item for item in tree.interface.items_tree
            if item.item_type == "SOCKET"
            and item.in_out == "INPUT"
            and item.identifier == identifier
        ),
        None,
    )


def _group_input(tree):
    node = next(
        (candidate for candidate in tree.nodes if candidate.bl_idname == "NodeGroupInput"),
        None,
    )
    return node or tree.nodes.new("NodeGroupInput")


def _assigned_object(socket):
    value = getattr(socket, "default_value", None)
    return value if isinstance(value, bpy.types.Object) else None


def _expose_socket(tree, socket, obj):
    """Return the interface socket feeding ``socket``, creating it when needed."""
    for link in socket.links:
        if link.from_node.bl_idname != "NodeGroupInput":
            continue
        interface_socket = _interface_input(tree, link.from_socket.identifier)
        if interface_socket is not None:
            interface_socket.default_value = obj
            return interface_socket, False

    interface_socket = tree.interface.new_socket(
        name=obj.name,
        in_out="INPUT",
        socket_type="NodeSocketObject",
    )
    interface_socket.default_value = obj
    output = _group_input(tree).outputs.get(interface_socket.identifier)
    if output is None:
        tree.interface.active = interface_socket
        output = _group_input(tree).outputs.get(interface_socket.identifier)
    if output is None:
        tree.interface.remove(interface_socket)
        raise RuntimeError("Blender did not create the corresponding Group Input socket")
    tree.links.new(output, socket)
    return interface_socket, True


def _editor_path(context):
    space = getattr(context, "space_data", None)
    if getattr(space, "type", None) != "NODE_EDITOR":
        return []
    return list(getattr(space, "path", ()))


def _set_modifier_object_input(modifier, identifier, obj):
    """Set a modifier input using Blender 5.2 RNA, with the legacy fallback."""
    properties = getattr(modifier, "properties", None)
    inputs = getattr(properties, "inputs", None)
    modifier_input = getattr(inputs, identifier, None) if inputs is not None else None
    if modifier_input is not None and hasattr(modifier_input, "value"):
        modifier_input.value = obj
        return
    try:
        modifier[identifier] = obj
    except TypeError as exc:
        raise RuntimeError(f"Could not assign modifier input {identifier}") from exc


def _owning_modifier(context, root_tree):
    owner = getattr(getattr(context, "space_data", None), "id", None)
    if not isinstance(owner, bpy.types.Object):
        owner = getattr(context, "active_object", None)
    if not isinstance(owner, bpy.types.Object):
        return None
    active = getattr(owner.modifiers, "active", None)
    if active is not None and active.type == "NODES" and active.node_group == root_tree:
        return active
    return next(
        (
            modifier for modifier in owner.modifiers
            if modifier.type == "NODES" and modifier.node_group == root_tree
        ),
        None,
    )


def promote_node_object_inputs(context, node):
    """Promote assigned Object inputs from ``node`` to the modifier-level group."""
    tree = getattr(context.space_data, "edit_tree", None)
    if tree is None or node.id_data != tree:
        raise ValueError("The node must belong to the currently edited Geometry Nodes tree")

    candidates = [
        socket for socket in node.inputs
        if socket.type == "OBJECT" and _assigned_object(socket) is not None
    ]
    if not candidates:
        return 0, 0

    promoted = []
    created = 0
    for socket in candidates:
        obj = _assigned_object(socket)
        interface_socket, was_created = _expose_socket(tree, socket, obj)
        promoted.append((interface_socket.identifier, obj))
        created += int(was_created)

    path = _editor_path(context)
    if path and getattr(path[-1], "node_tree", None) == tree:
        for index in range(len(path) - 1, 0, -1):
            parent_tree = path[index - 1].node_tree
            parent_node = path[index].node
            next_promoted = []
            for identifier, obj in promoted:
                parent_socket = parent_node.inputs.get(identifier)
                if parent_socket is None:
                    raise RuntimeError("Could not resolve the enclosing group input")
                parent_socket.default_value = obj
                interface_socket, was_created = _expose_socket(parent_tree, parent_socket, obj)
                next_promoted.append((interface_socket.identifier, obj))
                created += int(was_created)
            tree = parent_tree
            promoted = next_promoted

    modifier = _owning_modifier(context, tree)
    if modifier is not None:
        for identifier, obj in promoted:
            _set_modifier_object_input(modifier, identifier, obj)

    return len(candidates), created


def promote_root_node_object_inputs(tree, node, modifier=None):
    """Promote a node already known to live in a modifier's root node tree."""
    if node.id_data != tree:
        raise ValueError("The node must belong to the supplied Geometry Nodes tree")
    candidates = [
        socket for socket in node.inputs
        if socket.type == "OBJECT" and _assigned_object(socket) is not None
    ]
    created = 0
    for socket in candidates:
        obj = _assigned_object(socket)
        interface_socket, was_created = _expose_socket(tree, socket, obj)
        if modifier is not None:
            _set_modifier_object_input(modifier, interface_socket.identifier, obj)
        created += int(was_created)
    return len(candidates), created


def promote_nodes_object_inputs(context, nodes):
    sockets = 0
    created = 0
    for node in nodes:
        node_sockets, node_created = promote_node_object_inputs(context, node)
        sockets += node_sockets
        created += node_created
    return sockets, created


class NO3D_CAD_OT_promote_object_inputs(Operator):
    bl_idname = ids.PROMOTE_OBJECT_INPUTS_OT
    bl_label = "Expose Object Inputs in Modifier"
    bl_description = (
        "Expose assigned Object inputs from selected nodes through enclosing groups "
        "while preserving their Object values"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        space = getattr(context, "space_data", None)
        tree = getattr(space, "edit_tree", None)
        return (
            context.area is not None
            and context.area.type == "NODE_EDITOR"
            and getattr(space, "tree_type", None) == "GeometryNodeTree"
            and tree is not None
            and any(
                node.select
                and any(socket.type == "OBJECT" and _assigned_object(socket) for socket in node.inputs)
                for node in tree.nodes
            )
        )

    def execute(self, context):
        tree = context.space_data.edit_tree
        selected = [node for node in tree.nodes if node.select]
        try:
            sockets, created = promote_nodes_object_inputs(context, selected)
        except (ValueError, RuntimeError) as exc:
            self.report({"WARNING"}, str(exc))
            return {"CANCELLED"}
        if sockets == 0:
            self.report({"WARNING"}, "Selected nodes have no assigned Object inputs")
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"Exposed {sockets} Object input(s); created {created} group interface socket(s)",
        )
        return {"FINISHED"}


def draw_node_action(layout):
    layout.operator(ids.PROMOTE_OBJECT_INPUTS_OT, icon="NODE_SOCKET_OBJECT")


CLASSES = (NO3D_CAD_OT_promote_object_inputs,)
