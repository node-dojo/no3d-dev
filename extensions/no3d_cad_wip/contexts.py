"""Resolve the Blender object intended by the current authoring surface."""

from __future__ import annotations

import bpy


def active_geometry_nodes_modifier(obj):
    if obj is None:
        return None
    active = getattr(obj.modifiers, "active", None)
    if active is not None and active.type == "NODES" and active.node_group is not None:
        return active
    return next(
        (modifier for modifier in obj.modifiers if modifier.type == "NODES" and modifier.node_group),
        None,
    )


def object_from_context(context):
    """Prefer the Object whose Geometry Nodes graph the Node Editor displays."""
    space = getattr(context, "space_data", None)
    if (
        space is not None
        and getattr(space, "type", None) == "NODE_EDITOR"
        and getattr(space, "tree_type", None) == "GeometryNodeTree"
    ):
        editor_id = getattr(space, "id", None)
        if isinstance(editor_id, bpy.types.Object):
            return editor_id
        tree = edited_geometry_tree(context)
        if tree is not None:
            candidates = []
            scene = getattr(context, "scene", None)
            for obj in scene.objects if scene is not None else ():
                for modifier in obj.modifiers:
                    if modifier.type == "NODES" and _tree_contains(modifier.node_group, tree):
                        candidates.append(obj)
                        break
            if len(candidates) == 1:
                return candidates[0]
        return None
    return getattr(context, "active_object", None)


def edited_geometry_tree(context):
    """Return the Geometry Nodes tree currently open for direct node authoring."""
    space = getattr(context, "space_data", None)
    if (
        space is not None
        and getattr(space, "type", None) == "NODE_EDITOR"
        and getattr(space, "tree_type", None) == "GeometryNodeTree"
    ):
        tree = getattr(space, "edit_tree", None)
        if tree is not None and tree.bl_idname == "GeometryNodeTree":
            return tree
    return None


def node_cursor_location(context):
    space = getattr(context, "space_data", None)
    location = getattr(space, "cursor_location", None)
    return tuple(location) if location is not None else (0.0, 0.0)


def _tree_contains(root, target):
    pending = [root] if root is not None else []
    visited = set()
    while pending:
        tree = pending.pop()
        pointer = tree.as_pointer()
        if pointer in visited:
            continue
        visited.add(pointer)
        if tree == target:
            return True
        pending.extend(
            node.node_tree
            for node in tree.nodes
            if node.bl_idname == "GeometryNodeGroup" and node.node_tree is not None
        )
    return False


def geometry_owner_from_context(context):
    """Resolve an owner suitable for an action that edits a Geometry Nodes graph."""
    obj = object_from_context(context)
    if active_geometry_nodes_modifier(obj) is not None:
        return obj
    if obj is not None and obj.get("no3d_feature_tool") and obj.parent is not None:
        if active_geometry_nodes_modifier(obj.parent) is not None:
            return obj.parent
    return obj
