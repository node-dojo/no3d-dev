"""GPU skin for borderless Canvas Editor cards."""

from __future__ import annotations

import os
import textwrap

import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader

from .model import (
    GROUP_NODE_IDNAME,
    IMAGE_NODE_IDNAME,
    NOTE_NODE_IDNAME,
    SETTINGS_HEIGHT,
    TREE_IDNAME,
)


_DRAW_HANDLE = None
_INTERACTION_WINDOWS: set[int] = set()
_ENABLED = False

CARD_TYPES = {IMAGE_NODE_IDNAME, NOTE_NODE_IDNAME, GROUP_NODE_IDNAME}


def is_canvas_context(context) -> bool:
    space = getattr(context, "space_data", None)
    return bool(
        space
        and space.type == "NODE_EDITOR"
        and getattr(space, "tree_type", "") == TREE_IDNAME
        and getattr(space, "edit_tree", None)
    )


def card_view_bounds(node):
    location = node.location_absolute
    # `width`/`height` are requested layout values. `dimensions` is Blender's
    # evaluated on-screen node rectangle after headers, sockets, and UI scale.
    # The skin must follow the latter or native selection/hit geometry drifts.
    width = max(1.0, float(node.dimensions.x or node.width))
    height = max(1.0, float(node.dimensions.y or node.height))
    dpi_factor = max(1.0, float(bpy.context.preferences.system.dpi) / 72.0)
    left = (location.x + 1.0) * dpi_factor
    top = (location.y + 1.0) * dpi_factor
    # This is Blender/Node Wrangler's native node hit rectangle convention:
    # DPI-scaled top-left location plus evaluated dimensions downward.
    return left, top - height, left + width, top


def card_region_bounds(context, node):
    x0, y0, x1, y1 = card_view_bounds(node)
    view2d = context.region.view2d
    left, bottom = view2d.view_to_region(x0, y0, clip=False)
    right, top = view2d.view_to_region(x1, y1, clip=False)
    return float(left), float(bottom), float(right), float(top)


def point_in_bounds(x, y, bounds):
    left, bottom, right, top = bounds
    return left <= x <= right and bottom <= y <= top


def plus_bounds(bounds):
    left, bottom, right, top = bounds
    size = max(18.0, min(26.0, (right - left) * 0.08))
    pad = 7.0
    return right - size - pad, bottom + pad, right - pad, bottom + size + pad


def node_at_region_point(context, x, y):
    if not is_canvas_context(context):
        return None
    for node in reversed(list(context.space_data.edit_tree.nodes)):
        if node.bl_idname in CARD_TYPES and point_in_bounds(x, y, card_region_bounds(context, node)):
            return node
    return None


def _draw_rect(bounds, color):
    left, bottom, right, top = bounds
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(
        shader,
        "TRI_FAN",
        {"pos": ((left, bottom), (right, bottom), (right, top), (left, top))},
    )
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _draw_outline(bounds, color, width=1.0):
    left, bottom, right, top = bounds
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(
        shader,
        "LINE_LOOP",
        {"pos": ((left, bottom), (right, bottom), (right, top), (left, top))},
    )
    gpu.state.line_width_set(width)
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.line_width_set(1.0)


def _draw_image(image, bounds):
    status, detail = image_status(image)
    if status != "READY":
        _draw_rect(bounds, (0.075, 0.075, 0.075, 1.0))
        left, bottom, _right, top = bounds
        _draw_text(status.replace("_", " ").title(), left + 14.0, top - 30.0, 14)
        if detail:
            _draw_text(
                detail,
                left + 14.0,
                max(bottom + 14.0, top - 54.0),
                10,
                (0.58, 0.58, 0.58, 1.0),
            )
        return
    try:
        texture = gpu.texture.from_image(image)
        shader = gpu.shader.from_builtin("IMAGE")
        left, bottom, right, top = bounds
        batch = batch_for_shader(
            shader,
            "TRI_FAN",
            {
                "pos": ((left, bottom), (right, bottom), (right, top), (left, top)),
                "texCoord": ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
            },
        )
        shader.bind()
        shader.uniform_sampler("image", texture)
        batch.draw(shader)
    except Exception as exc:
        _draw_rect(bounds, (0.075, 0.075, 0.075, 1.0))
        left, _bottom, _right, top = bounds
        _draw_text("Texture unavailable", left + 14.0, top - 30.0, 14)
        _draw_text(
            str(exc)[:72],
            left + 14.0,
            top - 54.0,
            10,
            (0.58, 0.58, 0.58, 1.0),
        )


def image_status(image):
    if image is None:
        return "NO_IMAGE", "Choose or assign a Blender Image"
    if image.size[0] <= 0 or image.size[1] <= 0:
        return "NOT_LOADED", image.name
    if image.source == "FILE" and not getattr(image, "packed_file", None):
        filepath = bpy.path.abspath(image.filepath)
        if filepath and not os.path.isfile(filepath):
            return "MISSING", os.path.basename(filepath) or image.name
    return "READY", ""


def _draw_text(text, x, y, size=14, color=(0.88, 0.88, 0.88, 1.0)):
    font_id = 0
    blf.size(font_id, size)
    blf.color(font_id, *color)
    blf.position(font_id, x, y, 0)
    blf.draw(font_id, text)


def _draw_note(node, bounds):
    _draw_rect(bounds, (0.105, 0.105, 0.105, 1.0))
    left, bottom, right, top = bounds
    source = node.text.as_string() if node.text else ""
    if not source:
        _draw_text("Write…", left + 14.0, top - 30.0, 14, (0.52, 0.52, 0.52, 1.0))
        return
    lines = []
    for paragraph in source.splitlines() or [""]:
        lines.extend(textwrap.wrap(paragraph, width=max(16, int((right - left) / 8.5))) or [""])
    available = max(1, int((top - bottom - 35.0) / 20.0))
    y = top - 30.0
    for line in lines[:available]:
        _draw_text(line, left + 14.0, y, 14)
        y -= 20.0
    if len(lines) > available:
        _draw_text("…", right - 22.0, bottom + 10.0, 16, (0.62, 0.62, 0.62, 1.0))


def _draw_group(node, bounds):
    _draw_rect(bounds, (0.075, 0.085, 0.105, 1.0))
    left, bottom, right, top = bounds
    _draw_text("NESTED CANVAS", left + 14.0, top - 27.0, 11, (0.55, 0.68, 0.86, 1.0))
    name = node.node_tree.name if node.node_tree else "Untitled Canvas"
    _draw_text(name, left + 14.0, top - 55.0, 17)
    _draw_text("Double-click to enter", left + 14.0, bottom + 16.0, 11, (0.58, 0.58, 0.58, 1.0))


def _draw_footer(node, bounds):
    left, bottom, right, _top = bounds
    requested_height = max(1.0, float(node.canvas_media_height) + SETTINGS_HEIGHT)
    footer_fraction = SETTINGS_HEIGHT / requested_height
    footer_top = bottom + (bounds[3] - bottom) * footer_fraction
    footer = (left, bottom, right, footer_top)
    _draw_rect(footer, (0.045, 0.045, 0.045, 0.98))
    if node.bl_idname == IMAGE_NODE_IDNAME:
        source = node.image.name if node.image else "No image selected"
        _draw_text(source, left + 12.0, footer_top - 24.0, 12)
        _draw_text("Image datablock", left + 12.0, footer_top - 47.0, 10, (0.58, 0.58, 0.58, 1.0))
    elif node.bl_idname == NOTE_NODE_IDNAME:
        source = node.text.name if node.text else "No text datablock"
        _draw_text(source, left + 12.0, footer_top - 24.0, 12)
        _draw_text("Text datablock", left + 12.0, footer_top - 47.0, 10, (0.58, 0.58, 0.58, 1.0))
    else:
        _draw_text("Canvas NodeTree", left + 12.0, footer_top - 28.0, 11)


def _draw_anchor(x, y, active):
    radius = 5.0 if active else 3.5
    color = (0.78, 0.82, 0.88, 1.0) if active else (0.46, 0.49, 0.54, 1.0)
    segments = 20
    import math

    points = [(x, y)]
    points.extend(
        (x + math.cos(i * math.tau / segments) * radius, y + math.sin(i * math.tau / segments) * radius)
        for i in range(segments + 1)
    )
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(shader, "TRI_FAN", {"pos": points})
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _draw_card(context, node):
    bounds = card_region_bounds(context, node)
    left, bottom, right, top = bounds
    if right < 0 or top < 0 or left > context.region.width or bottom > context.region.height:
        return

    footer_pixels = 0.0
    if node.canvas_settings_expanded:
        requested_height = max(1.0, float(node.canvas_media_height) + SETTINGS_HEIGHT)
        footer_pixels = (top - bottom) * SETTINGS_HEIGHT / requested_height
    content_bounds = (left, bottom + footer_pixels, right, top)

    if node.bl_idname == IMAGE_NODE_IDNAME:
        _draw_image(node.image, content_bounds)
    elif node.bl_idname == NOTE_NODE_IDNAME:
        _draw_note(node, content_bounds)
    else:
        _draw_group(node, content_bounds)

    if node.canvas_settings_expanded:
        _draw_footer(node, bounds)

    hovered = context.window_manager.canvas_editor_hover_uuid == node.canvas_uuid
    if node.select:
        _draw_outline(bounds, (0.84, 0.66, 0.16, 0.95), 1.5)

    if hovered or node.select:
        # Blender places native sockets immediately below the hidden header.
        # These quiet anchors visually reveal those retained hit targets.
        anchor_y = top - min(34.0, max(18.0, (top - bottom) * 0.14))
        _draw_anchor(left, anchor_y, hovered)
        _draw_anchor(right, anchor_y, hovered)

        pb = plus_bounds(bounds)
        _draw_rect(pb, (0.02, 0.02, 0.02, 0.78))
        glyph = "-" if node.canvas_settings_expanded else "+"
        _draw_text(glyph, pb[0] + 5.0, pb[1] + 3.0, 15)


def draw_canvas_cards():
    context = bpy.context
    if not is_canvas_context(context) or getattr(context, "region", None) is None:
        return
    gpu.state.blend_set("ALPHA")
    try:
        for node in context.space_data.edit_tree.nodes:
            if node.bl_idname in CARD_TYPES:
                _draw_card(context, node)
    finally:
        gpu.state.blend_set("NONE")


def install_draw_handler() -> None:
    global _DRAW_HANDLE, _ENABLED
    _ENABLED = True
    if _DRAW_HANDLE is None:
        _DRAW_HANDLE = bpy.types.SpaceNodeEditor.draw_handler_add(
            draw_canvas_cards,
            (),
            "WINDOW",
            "POST_PIXEL",
        )


def remove_draw_handler() -> None:
    global _DRAW_HANDLE, _ENABLED
    _ENABLED = False
    if _DRAW_HANDLE is not None:
        bpy.types.SpaceNodeEditor.draw_handler_remove(_DRAW_HANDLE, "WINDOW")
        _DRAW_HANDLE = None
    _INTERACTION_WINDOWS.clear()


def interaction_is_running(window) -> bool:
    return window.as_pointer() in _INTERACTION_WINDOWS


def is_enabled() -> bool:
    return _ENABLED


def mark_interaction_running(window) -> None:
    _INTERACTION_WINDOWS.add(window.as_pointer())


def mark_interaction_stopped(window) -> None:
    _INTERACTION_WINDOWS.discard(window.as_pointer())
