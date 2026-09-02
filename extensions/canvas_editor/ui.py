"""Native entry points and selected-card inspector for Canvas Editor."""

from __future__ import annotations

import bpy
from bpy.types import Panel

from .model import GROUP_NODE_IDNAME, IMAGE_NODE_IDNAME, NOTE_NODE_IDNAME, TREE_IDNAME


class NO3D_CANVAS_PT_canvas(Panel):
    bl_idname = "NO3D_CANVAS_PT_canvas"
    bl_label = "Canvas Editor"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "Canvas"

    @classmethod
    def poll(cls, context):
        return getattr(context.space_data, "tree_type", "") == TREE_IDNAME

    def draw(self, context):
        layout = self.layout
        tree = getattr(context.space_data, "edit_tree", None)
        layout.label(text=tree.name if tree else "Untitled Canvas", icon="NODETREE")

        create = layout.column(align=True)
        create.operator_context = "INVOKE_DEFAULT"
        create.operator("no3d_canvas.add_image", icon="IMAGE_DATA")
        create.operator("no3d_canvas.add_note", icon="TEXT")
        create.operator("no3d_canvas.add_nested", icon="NODETREE")
        create.operator("no3d_canvas.add_frame", icon="NODE")

        node = getattr(context, "active_node", None)
        if node is None:
            return
        if node.bl_idname not in {IMAGE_NODE_IDNAME, NOTE_NODE_IDNAME, GROUP_NODE_IDNAME}:
            return

        layout.separator()
        layout.label(text="Selected Card")
        layout.prop(node, "canvas_settings_expanded", toggle=True)

        if node.bl_idname == IMAGE_NODE_IDNAME:
            layout.template_ID(node, "image", open="image.open")
            row = layout.row(align=True)
            row.operator_context = "INVOKE_DEFAULT"
            replace = row.operator("no3d_canvas.add_image", text="Replace", icon="FILE_FOLDER")
            replace.replace_node_uuid = node.canvas_uuid
            row.operator("no3d_canvas.reload_image", text="Reload", icon="FILE_REFRESH")
            layout.operator("no3d_canvas.refresh_image_aspect", icon="FULLSCREEN_ENTER")
            layout.operator("no3d_canvas.open_image_editor", icon="IMAGE_DATA")
        elif node.bl_idname == NOTE_NODE_IDNAME:
            layout.operator("no3d_canvas.edit_note", icon="TEXT")
            layout.template_ID(node, "text", new="text.new", unlink="text.unlink")
            if node.text:
                layout.prop(node.text, "name", text="Name")
                layout.label(text="Edit the Text datablock in a Text Editor")
        elif node.bl_idname == GROUP_NODE_IDNAME and node.node_tree:
            layout.prop(node.node_tree, "name", text="Canvas")


def draw_node_add_menu(self, context):
    if getattr(context.space_data, "tree_type", "") != TREE_IDNAME:
        return
    layout = self.layout
    layout.separator()
    layout.operator_context = "INVOKE_DEFAULT"
    layout.operator("no3d_canvas.add_image", icon="IMAGE_DATA")
    layout.operator("no3d_canvas.add_note", icon="TEXT")
    layout.operator("no3d_canvas.add_nested", icon="NODETREE")
    layout.operator("no3d_canvas.add_frame", icon="NODE")


class NO3D_CANVAS_PT_text_companion(Panel):
    bl_idname = "NO3D_CANVAS_PT_text_companion"
    bl_label = "Canvas Note"
    bl_space_type = "TEXT_EDITOR"
    bl_region_type = "UI"
    bl_category = "Canvas"

    def draw(self, context):
        self.layout.operator("no3d_canvas.return_to_canvas", icon="NODETREE")


class NO3D_CANVAS_PT_image_companion(Panel):
    bl_idname = "NO3D_CANVAS_PT_image_companion"
    bl_label = "Canvas Image"
    bl_space_type = "IMAGE_EDITOR"
    bl_region_type = "UI"
    bl_category = "Canvas"

    def draw(self, context):
        self.layout.operator("no3d_canvas.return_to_canvas", icon="NODETREE")


UI_CLASSES = (
    NO3D_CANVAS_PT_canvas,
    NO3D_CANVAS_PT_text_companion,
    NO3D_CANVAS_PT_image_companion,
)


def register_menus():
    bpy.types.NODE_MT_add.append(draw_node_add_menu)


def unregister_menus():
    try:
        bpy.types.NODE_MT_add.remove(draw_node_add_menu)
    except (AttributeError, ValueError):
        pass
