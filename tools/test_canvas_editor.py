"""Focused Blender 5.2 data-model and persistence probe for Canvas Editor."""

from __future__ import annotations

import os
import sys
import tempfile

import bpy


PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTENSIONS = os.path.join(PROJECT, "extensions")
if EXTENSIONS not in sys.path:
    sys.path.insert(0, EXTENSIONS)

import canvas_editor
from canvas_editor.model import (
    GROUP_NODE_IDNAME,
    IMAGE_NODE_IDNAME,
    NOTE_NODE_IDNAME,
    TREE_IDNAME,
    ensure_link_identity,
    ensure_scene_canvas,
)
from canvas_editor.drawing import image_status
from canvas_editor.operators import create_image_card


canvas_editor.register()

tree = ensure_scene_canvas(bpy.context.scene)
assert tree.bl_idname == TREE_IDNAME
assert tree.canvas_uuid

# Image creation is transactional: bad input leaves the Canvas unchanged.
node_count = len(tree.nodes)
try:
    create_image_card(tree, "", (0.0, 0.0))
except RuntimeError as exc:
    assert "Choose an image" in str(exc)
else:
    raise AssertionError("Empty image creation unexpectedly succeeded")
assert len(tree.nodes) == node_count

missing_path = os.path.join(tempfile.gettempdir(), "canvas-editor-missing.png")
try:
    create_image_card(tree, missing_path, (0.0, 0.0))
except RuntimeError as exc:
    assert "does not exist" in str(exc)
else:
    raise AssertionError("Missing image creation unexpectedly succeeded")
assert len(tree.nodes) == node_count

fixture_path = os.path.join(tempfile.gettempdir(), "canvas-editor-image-fixture.png")
fixture = bpy.data.images.new("Canvas Image Fixture Source", width=32, height=16)
fixture.filepath_raw = fixture_path
fixture.file_format = "PNG"
fixture.save()
bpy.data.images.remove(fixture)

image_node = create_image_card(tree, fixture_path, (-300.0, 100.0))
assert image_node.image is not None
assert tuple(image_node.location) == (-300.0, 100.0)
assert image_node.canvas_media_height == image_node.canvas_card_width / 2.0
assert image_status(image_node.image)[0] == "READY"

# Replacing changes the source without changing card identity or node count.
replacement_path = os.path.join(tempfile.gettempdir(), "canvas-editor-image-replacement.png")
replacement = bpy.data.images.new("Canvas Image Fixture Replacement", width=16, height=32)
replacement.filepath_raw = replacement_path
replacement.file_format = "PNG"
replacement.save()
bpy.data.images.remove(replacement)
before_replace_count = len(tree.nodes)
original_uuid = image_node.canvas_uuid
replaced = create_image_card(
    tree,
    replacement_path,
    (999.0, 999.0),
    replace_node_uuid=original_uuid,
)
assert replaced == image_node
assert replaced.canvas_uuid == original_uuid
assert len(tree.nodes) == before_replace_count
assert tuple(replaced.location) == (-300.0, 100.0)
assert replaced.canvas_media_height == replaced.canvas_card_width * 2.0

image_node.canvas_settings_expanded = True

note_node = tree.nodes.new(NOTE_NODE_IDNAME)
assert note_node.text is not None
assert note_node.text.as_string() == ""
note_node.text.write("# Canvas Editor V0\n\nBorderless cards over native nodes.")
note_node.location = (100.0, 100.0)

link = tree.links.new(image_node.outputs[0], note_node.inputs[0])
tree.update()
link_identity = ensure_link_identity(tree, link)
assert link_identity.uuid

frame = tree.nodes.new("NodeFrame")
frame.name = "Native Frame"
note_node.parent = frame

group = tree.nodes.new(GROUP_NODE_IDNAME)
group.location = (500.0, 100.0)
assert group.node_tree is not None
assert group.node_tree.bl_idname == TREE_IDNAME
assert group.node_tree.canvas_uuid

assert image_node.canvas_uuid
assert note_node.canvas_uuid
assert bpy.path.abspath(image_node.image.filepath) == replacement_path
assert note_node.text is not None
assert note_node.text.as_string().startswith("# Canvas Editor V0")
assert image_node.canvas_settings_expanded
assert len(tree.links) == 1
assert note_node.parent == frame

probe_path = os.path.join(tempfile.gettempdir(), "canvas_editor_v0_probe.blend")
bpy.ops.wm.save_as_mainfile(filepath=probe_path)
bpy.ops.wm.open_mainfile(filepath=probe_path)

tree = bpy.context.scene.canvas_editor_tree
assert tree is not None and tree.bl_idname == TREE_IDNAME
assert tree.canvas_uuid
assert len(tree.links) == 1
assert len(tree.canvas_link_identities) == 1
assert tree.canvas_link_identities[0].uuid

image_node = next(node for node in tree.nodes if node.bl_idname == IMAGE_NODE_IDNAME)
note_node = next(node for node in tree.nodes if node.bl_idname == NOTE_NODE_IDNAME)
group = next(node for node in tree.nodes if node.bl_idname == GROUP_NODE_IDNAME)
frame = tree.nodes.get("Native Frame")

assert image_node.image is not None
assert image_node.canvas_settings_expanded
assert note_node.text is not None
assert note_node.parent == frame
assert group.node_tree is not None and group.node_tree.bl_idname == TREE_IDNAME

canvas_editor.unregister()
assert not hasattr(bpy.types.Scene, "canvas_editor_tree")
assert not hasattr(bpy.types.WindowManager, "canvas_editor_hover_uuid")

print("CANVAS_EDITOR_V0_OK")
