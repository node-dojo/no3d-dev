"""General utilities for Object datablocks referenced by UI properties."""

from __future__ import annotations

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from . import ids


def object_from_button_context(context):
    """Return the Object held by the UI property under the context-menu click."""
    pointer = getattr(context, "button_pointer", None)
    prop = getattr(context, "button_prop", None)
    if pointer is None or prop is None:
        return None

    identifier = getattr(prop, "identifier", "")
    value = None
    if identifier:
        try:
            value = getattr(pointer, identifier)
        except (AttributeError, TypeError):
            try:
                value = pointer[identifier]
            except (KeyError, TypeError):
                pass
    return value if isinstance(value, bpy.types.Object) else None


def object_is_in_scene(obj, scene):
    return obj is not None and scene is not None and obj.name in scene.objects


def _collection_is_in_scene(collection, scene):
    return collection == scene.collection or any(
        candidate == collection for candidate in scene.collection.children_recursive
    )


def destination_collection(context, obj):
    scene = context.scene
    parent = obj.parent
    if parent is not None and object_is_in_scene(parent, scene):
        for collection in parent.users_collection:
            if _collection_is_in_scene(collection, scene):
                return collection

    active = context.active_object
    if active is not None and object_is_in_scene(active, scene):
        for collection in active.users_collection:
            if _collection_is_in_scene(collection, scene):
                return collection

    layer_collection = getattr(context.view_layer, "active_layer_collection", None)
    if layer_collection is not None and layer_collection.collection is not None:
        return layer_collection.collection
    return scene.collection


class NO3D_CAD_OT_relink_referenced_object(Operator):
    """Relink an existing referenced Object datablock to the current scene"""

    bl_idname = ids.RELINK_REFERENCED_OBJECT_OT
    bl_label = "Relink Object to Current Scene"
    bl_description = "Link the referenced Object datablock into the current scene without copying it"
    bl_options = {"REGISTER", "UNDO"}

    target_name: StringProperty(options={"HIDDEN"})

    def execute(self, context):
        obj = bpy.data.objects.get(self.target_name)
        if obj is None:
            self.report({"ERROR"}, "The referenced Object datablock no longer exists")
            return {"CANCELLED"}
        if object_is_in_scene(obj, context.scene):
            self.report({"INFO"}, f'"{obj.name}" is already in the current scene')
            return {"CANCELLED"}

        collection = destination_collection(context, obj)
        try:
            collection.objects.link(obj)
        except RuntimeError as exc:
            self.report({"ERROR"}, f"Could not relink object: {exc}")
            return {"CANCELLED"}

        obj.hide_set(False)
        obj.hide_viewport = False
        if obj.name in context.view_layer.objects:
            for selected in context.selected_objects:
                selected.select_set(False)
            obj.select_set(True)
            context.view_layer.objects.active = obj
        self.report({"INFO"}, f'Relinked "{obj.name}" to "{collection.name}"')
        return {"FINISHED"}


def draw_button_context(self, context):
    obj = object_from_button_context(context)
    if obj is None or object_is_in_scene(obj, context.scene):
        return
    self.layout.separator()
    operator = self.layout.operator(
        ids.RELINK_REFERENCED_OBJECT_OT,
        text="Relink Object to Current Scene",
        icon="OUTLINER_OB_MESH" if obj.type == "MESH" else "OBJECT_DATA",
    )
    operator.target_name = obj.name


CLASSES = (NO3D_CAD_OT_relink_referenced_object,)
