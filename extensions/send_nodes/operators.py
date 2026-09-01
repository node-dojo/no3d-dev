import re
import urllib.parse
import urllib.request
from pathlib import Path

import bpy
from bpy.props import BoolProperty, StringProperty

from .preferences import get_preferences


SUPPORTED_TREE_TYPES = {
    "GeometryNodeTree": "GeometryNodeGroup",
    "ShaderNodeTree": "ShaderNodeGroup",
    "CompositorNodeTree": "CompositorNodeGroup",
}
MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024
BLEND_FILE_HEADERS = (b"BLENDER", b"\x28\xb5\x2f\xfd")


def safe_filename(name):
    value = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    return value or "Node Group"


def active_share_group(context):
    space = context.space_data
    tree = getattr(space, "edit_tree", None)
    if tree is None:
        return None

    active = getattr(tree.nodes, "active", None)
    nested = getattr(active, "node_tree", None)
    if nested is not None and nested.bl_idname in SUPPORTED_TREE_TYPES:
        return nested

    if tree.bl_idname in SUPPORTED_TREE_TYPES and not tree.is_embedded_data:
        return tree
    return None


def normalize_download_url(value):
    url = value.strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Use an HTTP or HTTPS URL")

    if parsed.netloc.lower() == "github.com":
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 5 and parts[2] in {"blob", "raw"}:
            owner, repo, _kind, revision = parts[:4]
            remainder = "/".join(parts[4:])
            return f"https://raw.githubusercontent.com/{owner}/{repo}/{revision}/{remainder}"
    return url


def download_bundle(url):
    if not bpy.app.online_access:
        raise RuntimeError("Online Access is disabled in Blender Preferences")

    normalized = normalize_download_url(url)
    cache_root = Path(bpy.utils.extension_path_user(__package__, create=True)) / "downloads"
    cache_root.mkdir(parents=True, exist_ok=True)
    remote_name = Path(urllib.parse.unquote(urllib.parse.urlparse(normalized).path)).name
    if not remote_name.lower().endswith(".blend"):
        raise ValueError("The URL must point to a .blend file")
    destination = cache_root / safe_filename(remote_name)

    request = urllib.request.Request(normalized, headers={"User-Agent": "Blender Send Nodes"})
    with urllib.request.urlopen(request, timeout=30) as response:
        declared_size = response.headers.get("Content-Length")
        if declared_size and int(declared_size) > MAX_DOWNLOAD_BYTES:
            raise ValueError("The node bundle is larger than 256 MB")
        payload = response.read(MAX_DOWNLOAD_BYTES + 1)
    if len(payload) > MAX_DOWNLOAD_BYTES:
        raise ValueError("The node bundle is larger than 256 MB")
    if not payload.startswith(BLEND_FILE_HEADERS):
        raise ValueError("The downloaded file is not a Blender file")
    destination.write_bytes(payload)
    return destination


class SENDNODES_OT_export_group(bpy.types.Operator):
    bl_idname = "send_nodes.export_group"
    bl_label = "Send Active Node Group"
    bl_description = "Write the active node group and its dependencies as a native Blender bundle"
    bl_options = {"REGISTER"}

    replace_existing: BoolProperty(
        name="Replace Existing",
        description="Replace a bundle with the same node-group name",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return context.area and context.area.type == "NODE_EDITOR" and active_share_group(context)

    def execute(self, context):
        preferences = get_preferences(context)
        if not preferences or not preferences.publish_directory:
            self.report({"ERROR"}, "Choose a Publish Directory in the Send Nodes add-on preferences")
            return {"CANCELLED"}

        group = active_share_group(context)
        directory = Path(bpy.path.abspath(preferences.publish_directory)).expanduser()
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f"{safe_filename(group.name)}.blend"
        if destination.exists() and not self.replace_existing:
            self.report({"ERROR"}, "Bundle already exists; enable Replace Existing to update it")
            return {"CANCELLED"}

        bpy.data.libraries.write(
            str(destination),
            {group},
            path_remap="RELATIVE_ALL",
            fake_user=True,
            compress=True,
        )

        base_url = preferences.public_base_url.strip().rstrip("/")
        if base_url:
            quoted_name = urllib.parse.quote(destination.name)
            context.window_manager.clipboard = f"{base_url}/{quoted_name}"
            self.report({"INFO"}, f"Sent {group.name}; URL copied to clipboard")
        else:
            self.report({"INFO"}, f"Sent {group.name} to {destination}")
        return {"FINISHED"}


class SENDNODES_OT_receive_group(bpy.types.Operator):
    bl_idname = "send_nodes.receive_group"
    bl_label = "Receive Node Group"
    bl_description = "Download a native Blender node-group bundle and add it to the current node editor"
    bl_options = {"REGISTER", "UNDO"}

    url: StringProperty(name="Git URL", subtype="NONE")

    @classmethod
    def poll(cls, context):
        tree = getattr(context.space_data, "edit_tree", None)
        return bool(
            context.area
            and context.area.type == "NODE_EDITOR"
            and tree
            and tree.bl_idname in SUPPORTED_TREE_TYPES
        )

    def execute(self, context):
        try:
            bundle = download_bundle(self.url)
            current_tree = context.space_data.edit_tree
            before = set(bpy.data.node_groups)
            with bpy.data.libraries.load(str(bundle), link=False) as (data_from, data_to):
                data_to.node_groups = list(data_from.node_groups)
            imported = [group for group in bpy.data.node_groups if group not in before]
            compatible = [group for group in imported if group.bl_idname == current_tree.bl_idname]
            if not compatible:
                raise ValueError("The bundle contains no node group compatible with this editor")

            expected = bundle.stem.casefold()
            group = next(
                (item for item in compatible if safe_filename(item.name).casefold() == expected),
                compatible[0],
            )
            node = current_tree.nodes.new(SUPPORTED_TREE_TYPES[current_tree.bl_idname])
            node.node_tree = group
            node.location = context.space_data.cursor_location
            current_tree.nodes.active = node
            node.select = True
            self.report({"INFO"}, f"Received {group.name}")
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


classes = (
    SENDNODES_OT_export_group,
    SENDNODES_OT_receive_group,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
