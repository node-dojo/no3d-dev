"""Native Blender data model for Canvas Editor."""

from __future__ import annotations

import uuid

import bpy
from bpy.props import BoolProperty, CollectionProperty, FloatProperty, PointerProperty, StringProperty
from bpy.types import Image, Node, NodeCustomGroup, NodeSocket, NodeTree, PropertyGroup, Text


TREE_IDNAME = "NO3DCanvasTree"
SOCKET_IDNAME = "NO3DCanvasRelationshipSocket"
IMAGE_NODE_IDNAME = "NO3DCanvasImageNode"
NOTE_NODE_IDNAME = "NO3DCanvasNoteNode"
GROUP_NODE_IDNAME = "NO3DCanvasGroupNode"

CARD_WIDTH = 320.0
CARD_FALLBACK_HEIGHT = 200.0
CARD_MIN_HEIGHT = 96.0
SETTINGS_HEIGHT = 76.0
NATIVE_BASE_HEIGHT = 80.0
NATIVE_ROW_HEIGHT = 20.0


def new_uuid() -> str:
    return str(uuid.uuid4())


def ensure_uuid(node: Node) -> str:
    if hasattr(node, "canvas_uuid") and not node.canvas_uuid:
        node.canvas_uuid = new_uuid()
    return getattr(node, "canvas_uuid", "")


def image_card_height(image: Image | None, width: float = CARD_WIDTH) -> float:
    if image is None or image.size[0] <= 0 or image.size[1] <= 0:
        return CARD_FALLBACK_HEIGHT
    return max(CARD_MIN_HEIGHT, width * float(image.size[1]) / float(image.size[0]))


def sync_card_dimensions(node: Node) -> None:
    """Keep the real native hit rectangle aligned to the drawn card."""
    if not hasattr(node, "canvas_media_height"):
        return
    node.width = max(80.0, float(node.canvas_card_width))
    footer = SETTINGS_HEIGHT if node.canvas_settings_expanded else 0.0
    node.height = max(CARD_MIN_HEIGHT, float(node.canvas_media_height) + footer)


def update_card_dimensions(node, context) -> None:
    sync_card_dimensions(node)


def update_image_reference(node, context) -> None:
    node.refresh_aspect()


class NO3DCanvasLinkIdentity(PropertyGroup):
    uuid: StringProperty(name="Link UUID", default="")
    from_node_uuid: StringProperty(name="From Node UUID", default="")
    from_socket: StringProperty(name="From Socket", default="")
    to_node_uuid: StringProperty(name="To Node UUID", default="")
    to_socket: StringProperty(name="To Socket", default="")


def ensure_link_identity(tree: NodeTree, link) -> NO3DCanvasLinkIdentity:
    from_uuid = ensure_uuid(link.from_node)
    to_uuid = ensure_uuid(link.to_node)
    from_socket = link.from_socket.identifier
    to_socket = link.to_socket.identifier
    for record in tree.canvas_link_identities:
        if (
            record.from_node_uuid == from_uuid
            and record.from_socket == from_socket
            and record.to_node_uuid == to_uuid
            and record.to_socket == to_socket
        ):
            if not record.uuid:
                record.uuid = new_uuid()
            return record
    record = tree.canvas_link_identities.add()
    record.uuid = new_uuid()
    record.from_node_uuid = from_uuid
    record.from_socket = from_socket
    record.to_node_uuid = to_uuid
    record.to_socket = to_socket
    return record


class NO3DCanvasTree(NodeTree):
    bl_idname = TREE_IDNAME
    bl_label = "Canvas Editor"
    bl_icon = "NODETREE"

    canvas_uuid: StringProperty(name="Canvas UUID", default="")
    canvas_link_identities: CollectionProperty(type=NO3DCanvasLinkIdentity)

    def ensure_identity(self) -> str:
        if not self.canvas_uuid:
            self.canvas_uuid = new_uuid()
        return self.canvas_uuid

    def update(self):
        """Mirror native links into stable Canvas-owned identity records."""
        live_keys = set()
        for link in self.links:
            record = ensure_link_identity(self, link)
            live_keys.add(
                (record.from_node_uuid, record.from_socket, record.to_node_uuid, record.to_socket)
            )
        for index in range(len(self.canvas_link_identities) - 1, -1, -1):
            record = self.canvas_link_identities[index]
            key = (record.from_node_uuid, record.from_socket, record.to_node_uuid, record.to_socket)
            if key not in live_keys:
                self.canvas_link_identities.remove(index)

    @classmethod
    def get_from_context(cls, context):
        scene = getattr(context, "scene", None)
        tree = getattr(scene, "canvas_editor_tree", None) if scene else None
        return tree, scene, scene


class NO3DCanvasRelationshipSocket(NodeSocket):
    bl_idname = SOCKET_IDNAME
    bl_label = "Relationship"

    relation_kind: StringProperty(name="Relationship", default="related")

    def draw(self, context, layout, node, text):
        # The GPU skin progressively reveals the anchor. Keeping this layout
        # empty preserves Blender's real socket and hit target without labels.
        layout.label(text="")

    def draw_color(self, context, node):
        return (0.58, 0.62, 0.68, 1.0)


class CanvasCardMixin:
    canvas_uuid: StringProperty(name="Card UUID", default="")
    canvas_settings_expanded: BoolProperty(
        name="Show Settings",
        default=False,
        update=update_card_dimensions,
    )
    canvas_card_width: FloatProperty(name="Card Width", default=CARD_WIDTH, min=80.0)
    canvas_media_height: FloatProperty(
        name="Content Height",
        default=CARD_FALLBACK_HEIGHT,
        min=CARD_MIN_HEIGHT,
    )

    def _init_card(self):
        ensure_uuid(self)
        self.inputs.new(SOCKET_IDNAME, "In")
        self.outputs.new(SOCKET_IDNAME, "Out")
        self.label = ""
        self.use_custom_color = True
        self.color = (0.035, 0.035, 0.035)
        sync_card_dimensions(self)

    def draw_buttons(self, context, layout):
        # Blender derives a normal custom node's evaluated hit rectangle from
        # its UILayout and ignores arbitrary height requests when the body is
        # empty. Blank rows are structural spacers beneath the opaque GPU skin:
        # they keep native selection/framing geometry aligned to media aspect.
        target_height = self.canvas_media_height
        if self.canvas_settings_expanded:
            target_height += SETTINGS_HEIGHT
        rows = max(0, round((target_height - NATIVE_BASE_HEIGHT) / NATIVE_ROW_HEIGHT))
        column = layout.column(align=True)
        for _index in range(rows):
            column.label(text="")

    def draw_label(self):
        return ""


class NO3DCanvasImageNode(CanvasCardMixin, Node):
    bl_idname = IMAGE_NODE_IDNAME
    bl_label = "Image Card"
    bl_icon = "IMAGE_DATA"

    image: PointerProperty(
        name="Image",
        type=Image,
        update=update_image_reference,
    )

    def init(self, context):
        self._init_card()

    def refresh_aspect(self):
        self.canvas_media_height = image_card_height(self.image, self.canvas_card_width)
        sync_card_dimensions(self)

    @classmethod
    def poll(cls, node_tree):
        return node_tree is not None and node_tree.bl_idname == TREE_IDNAME


class NO3DCanvasNoteNode(CanvasCardMixin, Node):
    bl_idname = NOTE_NODE_IDNAME
    bl_label = "Note Card"
    bl_icon = "TEXT"

    text: PointerProperty(name="Text", type=Text)

    def init(self, context):
        self._init_card()
        self.canvas_card_width = 280.0
        self.canvas_media_height = 180.0
        self.text = bpy.data.texts.new("Untitled Note")
        sync_card_dimensions(self)

    @classmethod
    def poll(cls, node_tree):
        return node_tree is not None and node_tree.bl_idname == TREE_IDNAME


class NO3DCanvasGroupNode(CanvasCardMixin, NodeCustomGroup):
    bl_idname = GROUP_NODE_IDNAME
    bl_label = "Nested Canvas"
    bl_icon = "NODETREE"

    def init(self, context):
        self._init_card()
        self.canvas_card_width = 220.0
        self.canvas_media_height = 120.0
        inner = bpy.data.node_groups.new("Untitled Canvas", TREE_IDNAME)
        inner.ensure_identity()
        self.node_tree = inner
        sync_card_dimensions(self)

    @classmethod
    def poll(cls, node_tree):
        return node_tree is not None and node_tree.bl_idname == TREE_IDNAME


NODE_CLASSES = (
    NO3DCanvasLinkIdentity,
    NO3DCanvasTree,
    NO3DCanvasRelationshipSocket,
    NO3DCanvasImageNode,
    NO3DCanvasNoteNode,
    NO3DCanvasGroupNode,
)


def ensure_scene_canvas(scene) -> NO3DCanvasTree:
    tree = getattr(scene, "canvas_editor_tree", None)
    if tree is None:
        tree = bpy.data.node_groups.new("Untitled Canvas", TREE_IDNAME)
        tree.ensure_identity()
        scene.canvas_editor_tree = tree
    elif not tree.canvas_uuid:
        tree.ensure_identity()
    return tree


def register_properties() -> None:
    bpy.types.Scene.canvas_editor_tree = PointerProperty(
        name="Active Canvas",
        type=NO3DCanvasTree,
    )
    bpy.types.WindowManager.canvas_editor_hover_uuid = StringProperty(
        name="Hovered Canvas Card",
        default="",
        options={"SKIP_SAVE"},
    )


def unregister_properties() -> None:
    if hasattr(bpy.types.WindowManager, "canvas_editor_hover_uuid"):
        del bpy.types.WindowManager.canvas_editor_hover_uuid
    if hasattr(bpy.types.Scene, "canvas_editor_tree"):
        del bpy.types.Scene.canvas_editor_tree
