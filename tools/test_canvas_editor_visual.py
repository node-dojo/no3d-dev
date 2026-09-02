"""Interactive visual acceptance probe; launches only in a factory-startup Blender."""

from __future__ import annotations

import os
import sys

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
from canvas_editor.operators import start_interaction


OUTPUT = os.path.join("/tmp", "canvas_editor_v0_visual.png")
BLEND = os.path.join("/tmp", "canvas_editor_v0_visual.blend")


def make_test_image():
    image = bpy.data.images.new("Borderless Media", width=640, height=360)
    pixels = [0.0] * (640 * 360 * 4)
    for y in range(360):
        for x in range(640):
            i = (y * 640 + x) * 4
            u = x / 639.0
            v = y / 359.0
            pixels[i] = 0.04 + 0.16 * u
            pixels[i + 1] = 0.09 + 0.34 * v
            pixels[i + 2] = 0.16 + 0.48 * (1.0 - u * v)
            pixels[i + 3] = 1.0
    image.pixels.foreach_set(pixels)
    image.update()
    return image


def setup():
    canvas_editor.register()
    window = bpy.context.window
    area = max(window.screen.areas, key=lambda item: item.width * item.height)
    area.type = "NODE_EDITOR"
    area.spaces.active.tree_type = TREE_IDNAME
    ensure_scene_canvas(bpy.context.scene)
    window.workspace["canvas_editor_workspace"] = True
    area.tag_redraw()
    bpy.app.timers.register(populate, first_interval=0.5)
    return None


def populate():
    window = bpy.context.window
    area = max(window.screen.areas, key=lambda item: item.width * item.height)
    region = next(region for region in area.regions if region.type == "WINDOW")
    tree = ensure_scene_canvas(bpy.context.scene)

    image_node = tree.nodes.new(IMAGE_NODE_IDNAME)
    image_node.image = make_test_image()
    image_node.location = (-430.0, 150.0)

    note_node = tree.nodes.new(NOTE_NODE_IDNAME)
    note_node.text.write("CANVAS EDITOR V0\n\nBorderless media and notes over Blender-native nodes, links, frames, and groups.")
    note_node.location = (20.0, 150.0)

    group_node = tree.nodes.new(GROUP_NODE_IDNAME)
    group_node.location = (390.0, 150.0)
    group_node.canvas_settings_expanded = True

    ensure_link_identity(tree, tree.links.new(image_node.outputs[0], note_node.inputs[0]))
    ensure_link_identity(tree, tree.links.new(note_node.outputs[0], group_node.inputs[0]))

    frame = tree.nodes.new("NodeFrame")
    frame.label = "Native Blender frame"
    frame.location = (-10.0, -170.0)

    start_interaction(window, area)
    with bpy.context.temp_override(window=window, area=area, region=region):
        if bpy.ops.node.view_all.poll():
            bpy.ops.node.view_all()
    bpy.ops.wm.save_as_mainfile(filepath=BLEND)
    area.tag_redraw()

    bpy.app.timers.register(capture, first_interval=2.0)
    return None


def capture():
    # `Window.event_simulate` is available under Blender's --debug flag and
    # dismisses the factory-startup splash without touching saved preferences.
    if hasattr(bpy.context.window, "event_simulate"):
        bpy.context.window.event_simulate("MOUSEMOVE", "NOTHING", x=40, y=40)
        bpy.context.window.event_simulate("LEFTMOUSE", "PRESS", x=40, y=40)
        bpy.context.window.event_simulate("LEFTMOUSE", "RELEASE", x=40, y=40)
    area = max(bpy.context.window.screen.areas, key=lambda item: item.width * item.height)
    region = next(region for region in area.regions if region.type == "WINDOW")
    with bpy.context.temp_override(window=bpy.context.window, area=area, region=region):
        from canvas_editor.drawing import card_region_bounds
        for node in area.spaces.active.edit_tree.nodes:
            if hasattr(node, "canvas_uuid"):
                print(
                    "CANVAS_CARD_GEOMETRY",
                    node.bl_idname,
                    tuple(node.location_absolute),
                    tuple(node.dimensions),
                    card_region_bounds(bpy.context, node),
                )
    area.tag_redraw()
    bpy.app.timers.register(capture_clean, first_interval=0.5)
    return None


def capture_clean():
    bpy.ops.screen.screenshot(filepath=OUTPUT, check_existing=False)
    print(f"CANVAS_EDITOR_VISUAL={OUTPUT}")
    bpy.app.timers.register(quit_blender, first_interval=0.5)
    return None


def quit_blender():
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(setup, first_interval=0.2)
