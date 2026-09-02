"""Operators for creating and interacting with Canvas Editor surfaces."""

from __future__ import annotations

import os

import bpy
from bpy.props import StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper

from . import drawing
from .model import (
    GROUP_NODE_IDNAME,
    IMAGE_NODE_IDNAME,
    NOTE_NODE_IDNAME,
    TREE_IDNAME,
    ensure_scene_canvas,
    image_card_height,
    sync_card_dimensions,
)


WORKSPACE_MARKER = "canvas_editor_workspace"


def active_canvas_tree(context):
    space = getattr(context, "space_data", None)
    if space and space.type == "NODE_EDITOR":
        tree = getattr(space, "edit_tree", None) or getattr(space, "node_tree", None)
        if tree and tree.bl_idname == TREE_IDNAME:
            return tree
    tree = getattr(context.scene, "canvas_editor_tree", None)
    if tree and tree.bl_idname == TREE_IDNAME:
        return tree
    return None


def canvas_location(context):
    space = getattr(context, "space_data", None)
    if space and space.type == "NODE_EDITOR":
        return tuple(space.cursor_location)
    return (0.0, 0.0)


def select_only(tree, node):
    for other in tree.nodes:
        other.select = False
    node.select = True
    tree.nodes.active = node


def configure_canvas_area(window, area, tree) -> None:
    area.type = "NODE_EDITOR"
    space = area.spaces.active
    space.tree_type = TREE_IDNAME
    space.show_region_ui = True
    window.scene.canvas_editor_tree = tree


def start_interaction(window, area) -> None:
    if drawing.interaction_is_running(window):
        return
    region = next((item for item in area.regions if item.type == "WINDOW"), None)
    if region is None:
        return
    try:
        with bpy.context.temp_override(window=window, area=area, region=region):
            bpy.ops.no3d_canvas.interact("INVOKE_DEFAULT")
    except RuntimeError:
        pass


class NO3D_CANVAS_OT_open(Operator):
    bl_idname = "no3d_canvas.open"
    bl_label = "Open Canvas"
    bl_description = "Open an untitled Canvas immediately in its own Blender window"
    bl_options = {"REGISTER"}

    def execute(self, context):
        tree = ensure_scene_canvas(context.scene)

        for window in context.window_manager.windows:
            if window.workspace.get(WORKSPACE_MARKER, False):
                area = max(window.screen.areas, key=lambda item: item.width * item.height)
                configure_canvas_area(window, area, tree)
                start_interaction(window, area)
                self.report({"INFO"}, "Canvas window is already open")
                return {"FINISHED"}

        if bpy.app.background:
            self.report({"ERROR"}, "Canvas windows require Blender's interactive UI")
            return {"CANCELLED"}

        before = {window.as_pointer() for window in context.window_manager.windows}
        bpy.ops.wm.window_new_main()
        created = [
            window
            for window in context.window_manager.windows
            if window.as_pointer() not in before
        ]
        if not created:
            self.report({"ERROR"}, "Blender did not create a Canvas window")
            return {"CANCELLED"}

        window = created[0]
        window.workspace[WORKSPACE_MARKER] = True
        if window.workspace.name.startswith("Workspace"):
            window.workspace.name = "Canvas Editor"
        area = max(window.screen.areas, key=lambda item: item.width * item.height)
        configure_canvas_area(window, area, tree)
        start_interaction(window, area)
        area.tag_redraw()
        return {"FINISHED"}


class NO3D_CANVAS_OT_add_image(Operator, ImportHelper):
    bl_idname = "no3d_canvas.add_image"
    bl_label = "Add Image Card"
    bl_description = "Choose an image and place it as a borderless Canvas card"
    bl_options = {"REGISTER", "UNDO"}

    filter_glob: StringProperty(default="*.png;*.jpg;*.jpeg;*.tif;*.tiff;*.exr;*.hdr;*.webp;*.bmp", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return active_canvas_tree(context) is not None

    def execute(self, context):
        tree = active_canvas_tree(context)
        try:
            image = bpy.data.images.load(self.filepath, check_existing=True)
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        node = tree.nodes.new(IMAGE_NODE_IDNAME)
        node.image = image
        node.name = os.path.basename(self.filepath)
        node.canvas_media_height = image_card_height(image, node.canvas_card_width)
        sync_card_dimensions(node)
        node.location = canvas_location(context)
        select_only(tree, node)
        context.area.tag_redraw()
        return {"FINISHED"}


class NO3D_CANVAS_OT_add_note(Operator):
    bl_idname = "no3d_canvas.add_note"
    bl_label = "Add Note"
    bl_description = "Create an untitled note without requiring metadata"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return active_canvas_tree(context) is not None

    def execute(self, context):
        tree = active_canvas_tree(context)
        node = tree.nodes.new(NOTE_NODE_IDNAME)
        node.location = canvas_location(context)
        select_only(tree, node)
        context.area.tag_redraw()
        return {"FINISHED"}


class NO3D_CANVAS_OT_add_frame(Operator):
    bl_idname = "no3d_canvas.add_frame"
    bl_label = "Add Frame"
    bl_description = "Add a native Blender node frame"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return active_canvas_tree(context) is not None

    def execute(self, context):
        tree = active_canvas_tree(context)
        node = tree.nodes.new("NodeFrame")
        node.label = ""
        node.name = "Frame"
        node.location = canvas_location(context)
        select_only(tree, node)
        context.area.tag_redraw()
        return {"FINISHED"}


class NO3D_CANVAS_OT_add_nested(Operator):
    bl_idname = "no3d_canvas.add_nested"
    bl_label = "Add Nested Canvas"
    bl_description = "Add a native custom group node containing another Canvas"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return active_canvas_tree(context) is not None

    def execute(self, context):
        tree = active_canvas_tree(context)
        node = tree.nodes.new(GROUP_NODE_IDNAME)
        node.location = canvas_location(context)
        select_only(tree, node)
        context.area.tag_redraw()
        return {"FINISHED"}


class NO3D_CANVAS_OT_refresh_image_aspect(Operator):
    bl_idname = "no3d_canvas.refresh_image_aspect"
    bl_label = "Fit Card to Image"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        node = getattr(context, "active_node", None)
        return node is not None and node.bl_idname == IMAGE_NODE_IDNAME

    def execute(self, context):
        context.active_node.refresh_aspect()
        context.area.tag_redraw()
        return {"FINISHED"}


class NO3D_CANVAS_OT_interact(Operator):
    bl_idname = "no3d_canvas.interact"
    bl_label = "Canvas Interaction Layer"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        if drawing.interaction_is_running(context.window):
            return {"CANCELLED"}
        drawing.mark_interaction_running(context.window)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if not drawing.is_enabled():
            if context.window:
                drawing.mark_interaction_stopped(context.window)
            return {"CANCELLED"}
        if context.window is None:
            return {"CANCELLED"}

        if event.type in {"ESC"} and event.value == "PRESS" and not drawing.is_canvas_context(context):
            drawing.mark_interaction_stopped(context.window)
            return {"CANCELLED"}

        if not drawing.is_canvas_context(context) or context.region is None:
            return {"PASS_THROUGH"}

        x = event.mouse_region_x
        y = event.mouse_region_y
        hovered = drawing.node_at_region_point(context, x, y)
        hover_uuid = hovered.canvas_uuid if hovered else ""
        if context.window_manager.canvas_editor_hover_uuid != hover_uuid:
            context.window_manager.canvas_editor_hover_uuid = hover_uuid
            context.area.tag_redraw()

        if (
            event.type == "LEFTMOUSE"
            and event.value == "PRESS"
            and hovered is not None
            and drawing.point_in_bounds(x, y, drawing.plus_bounds(drawing.card_region_bounds(context, hovered)))
        ):
            hovered.canvas_settings_expanded = not hovered.canvas_settings_expanded
            sync_card_dimensions(hovered)
            context.area.tag_redraw()
            return {"RUNNING_MODAL"}

        return {"PASS_THROUGH"}

    def cancel(self, context):
        if context.window:
            drawing.mark_interaction_stopped(context.window)


OPERATOR_CLASSES = (
    NO3D_CANVAS_OT_open,
    NO3D_CANVAS_OT_add_image,
    NO3D_CANVAS_OT_add_note,
    NO3D_CANVAS_OT_add_frame,
    NO3D_CANVAS_OT_add_nested,
    NO3D_CANVAS_OT_refresh_image_aspect,
    NO3D_CANVAS_OT_interact,
)
