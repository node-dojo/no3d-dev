"""Operators for creating and interacting with Canvas Editor surfaces."""

from __future__ import annotations

import os

import bpy
from bpy.props import FloatProperty, StringProperty
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
_COMPANION_AREAS: dict[int, int] = {}


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


def canvas_tree_by_uuid(canvas_uuid):
    for tree in bpy.data.node_groups:
        if tree.bl_idname == TREE_IDNAME and tree.canvas_uuid == canvas_uuid:
            return tree
    return None


def canvas_node_by_uuid(tree, node_uuid, node_type=None):
    if tree is None:
        return None
    for node in tree.nodes:
        if getattr(node, "canvas_uuid", "") != node_uuid:
            continue
        if node_type is None or node.bl_idname == node_type:
            return node
    return None


def create_image_card(tree, filepath, location, replace_node_uuid=""):
    """Load first, then create or replace a card as one validated transaction."""
    if tree is None:
        raise RuntimeError("The target Canvas is no longer available")
    if not filepath or not filepath.strip():
        raise RuntimeError("Choose an image file")

    resolved = bpy.path.abspath(filepath)
    if not os.path.isfile(resolved):
        raise RuntimeError(f"Image file does not exist: {resolved}")

    image = bpy.data.images.load(resolved, check_existing=True)
    node = canvas_node_by_uuid(tree, replace_node_uuid, IMAGE_NODE_IDNAME)
    if node is None:
        node = tree.nodes.new(IMAGE_NODE_IDNAME)
        node.location = location
    node.image = image
    node.name = os.path.basename(resolved)
    node.canvas_media_height = image_card_height(image, node.canvas_card_width)
    sync_card_dimensions(node)
    select_only(tree, node)
    return node


def _companion_area(window):
    pointer = _COMPANION_AREAS.get(window.as_pointer())
    if pointer:
        area = next((item for item in window.screen.areas if item.as_pointer() == pointer), None)
        if area is not None:
            return area
        _COMPANION_AREAS.pop(window.as_pointer(), None)
    return None


def ensure_companion_area(context):
    """Reuse our same-window companion area or split one from the Canvas."""
    area = _companion_area(context.window)
    if area is not None:
        return area

    before = {item.as_pointer() for item in context.screen.areas}
    try:
        with bpy.context.temp_override(
            window=context.window,
            screen=context.screen,
            area=context.area,
        ):
            result = bpy.ops.screen.area_split(direction="VERTICAL", factor=0.68)
        if "FINISHED" in result:
            area = next(
                (item for item in context.screen.areas if item.as_pointer() not in before),
                None,
            )
            if area is not None:
                _COMPANION_AREAS[context.window.as_pointer()] = area.as_pointer()
                return area
    except RuntimeError:
        pass

    # A narrow or unusual screen may refuse splitting. Switching the current
    # area remains a native, reversible fallback and never opens a new window.
    return context.area


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
    target_canvas_uuid: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    target_x: FloatProperty(options={"HIDDEN", "SKIP_SAVE"})
    target_y: FloatProperty(options={"HIDDEN", "SKIP_SAVE"})
    replace_node_uuid: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return active_canvas_tree(context) is not None

    def invoke(self, context, event):
        tree = active_canvas_tree(context)
        if tree is None:
            self.report({"ERROR"}, "No active Canvas")
            return {"CANCELLED"}
        tree.ensure_identity()
        self.target_canvas_uuid = tree.canvas_uuid
        self.target_x, self.target_y = canvas_location(context)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        tree = canvas_tree_by_uuid(self.target_canvas_uuid) or active_canvas_tree(context)
        try:
            create_image_card(
                tree,
                self.filepath,
                (self.target_x, self.target_y),
                self.replace_node_uuid,
            )
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if context.area:
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


class NO3D_CANVAS_OT_reload_image(Operator):
    bl_idname = "no3d_canvas.reload_image"
    bl_label = "Reload Image"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        node = getattr(context, "active_node", None)
        return node is not None and node.bl_idname == IMAGE_NODE_IDNAME and node.image is not None

    def execute(self, context):
        try:
            context.active_node.image.reload()
            context.active_node.refresh_aspect()
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        context.area.tag_redraw()
        return {"FINISHED"}


class NO3D_CANVAS_OT_open_image_editor(Operator):
    bl_idname = "no3d_canvas.open_image_editor"
    bl_label = "Open in Image Editor"

    @classmethod
    def poll(cls, context):
        node = getattr(context, "active_node", None)
        return node is not None and node.bl_idname == IMAGE_NODE_IDNAME and node.image is not None

    def execute(self, context):
        image = context.active_node.image
        area = ensure_companion_area(context)
        area.type = "IMAGE_EDITOR"
        area.spaces.active.image = image
        area.spaces.active.show_region_ui = True
        area.tag_redraw()
        return {"FINISHED"}


class NO3D_CANVAS_OT_edit_note(Operator):
    bl_idname = "no3d_canvas.edit_note"
    bl_label = "Edit Note"
    bl_description = "Edit this card's native Text datablock beside the Canvas"
    node_uuid: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return active_canvas_tree(context) is not None

    def execute(self, context):
        tree = active_canvas_tree(context)
        node = canvas_node_by_uuid(tree, self.node_uuid, NOTE_NODE_IDNAME)
        if node is None:
            node = getattr(context, "active_node", None)
        if node is None or node.bl_idname != NOTE_NODE_IDNAME or node.text is None:
            self.report({"ERROR"}, "Select a Note Card to edit")
            return {"CANCELLED"}

        area = ensure_companion_area(context)
        area.type = "TEXT_EDITOR"
        area.spaces.active.text = node.text
        area.spaces.active.show_region_ui = True
        area.tag_redraw()
        return {"FINISHED"}


class NO3D_CANVAS_OT_return_to_canvas(Operator):
    bl_idname = "no3d_canvas.return_to_canvas"
    bl_label = "Return to Canvas"
    bl_description = "Turn this companion editor back into the active Canvas"

    def execute(self, context):
        tree = ensure_scene_canvas(context.scene)
        configure_canvas_area(context.window, context.area, tree)
        start_interaction(context.window, context.area)
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
        self._timer = context.window_manager.event_timer_add(0.25, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if not drawing.is_enabled():
            self.cancel(context)
            return {"CANCELLED"}
        if context.window is None:
            self.cancel(context)
            return {"CANCELLED"}

        if event.type == "TIMER":
            for area in context.window.screen.areas:
                if area.type != "NODE_EDITOR":
                    continue
                space = area.spaces.active
                if getattr(space, "tree_type", "") == TREE_IDNAME:
                    area.tag_redraw()
            return {"PASS_THROUGH"}

        if event.type in {"ESC"} and event.value == "PRESS" and not drawing.is_canvas_context(context):
            self.cancel(context)
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
            and event.value == "DOUBLE_CLICK"
            and hovered is not None
            and hovered.bl_idname == NOTE_NODE_IDNAME
        ):
            bpy.ops.no3d_canvas.edit_note(node_uuid=hovered.canvas_uuid)
            return {"RUNNING_MODAL"}

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
        timer = getattr(self, "_timer", None)
        if timer is not None:
            context.window_manager.event_timer_remove(timer)
            self._timer = None
        if context.window:
            drawing.mark_interaction_stopped(context.window)


OPERATOR_CLASSES = (
    NO3D_CANVAS_OT_open,
    NO3D_CANVAS_OT_add_image,
    NO3D_CANVAS_OT_add_note,
    NO3D_CANVAS_OT_add_frame,
    NO3D_CANVAS_OT_add_nested,
    NO3D_CANVAS_OT_refresh_image_aspect,
    NO3D_CANVAS_OT_reload_image,
    NO3D_CANVAS_OT_open_image_editor,
    NO3D_CANVAS_OT_edit_note,
    NO3D_CANVAS_OT_return_to_canvas,
    NO3D_CANVAS_OT_interact,
)
