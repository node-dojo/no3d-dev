"""
No3d Asset Developer — Utility functions.

Frontmatter generation, thumbnail export, asset querying, dependency scanning.
"""

import json
import logging
import os
import re
from datetime import datetime

import bpy
from bpy.types import Context

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Asset querying
# ---------------------------------------------------------------------------

def get_selected_assets(context: Context) -> list:
    """Return the single active asset from the Asset Browser, or fall back to
    all visible assets in the file."""
    if hasattr(context, "id") and context.id:
        asset = context.id
        if hasattr(asset, "asset_data") and asset.asset_data:
            return [asset]
    return get_all_visible_assets(context)


def get_available_catalogs() -> list[str]:
    """Return catalog names from asset libraries in the current file."""
    catalogs: list[str] = []
    for catalog in bpy.data.asset_libraries:
        if hasattr(catalog, "name") and catalog.name:
            catalogs.append(catalog.name)
    try:
        if bpy.data.filepath:
            catalogs.append("Local File Catalogs")
    except Exception:
        pass
    if not catalogs:
        catalogs = ["Default"]
    return catalogs


def get_assets_by_catalog(catalog_name: str, asset_type_filter: str = "ALL") -> list:
    """Return assets belonging to *catalog_name* with optional type filter."""
    return get_all_visible_assets(None, asset_type_filter)


def get_all_visible_assets(context: Context | None, asset_type_filter: str = "ALL") -> list:
    """Return every marked asset in the current file, filtered by type."""
    assets: list = []

    if asset_type_filter in ("ALL", "OBJECT"):
        for obj in bpy.data.objects:
            if hasattr(obj, "asset_data") and obj.asset_data:
                assets.append(obj)

    if asset_type_filter in ("ALL", "MATERIAL"):
        for mat in bpy.data.materials:
            if hasattr(mat, "asset_data") and mat.asset_data:
                assets.append(mat)

    if asset_type_filter in ("ALL", "NODE_TREE"):
        for ng in bpy.data.node_groups:
            if hasattr(ng, "asset_data") and ng.asset_data:
                assets.append(ng)

    if asset_type_filter in ("ALL", "COLLECTION"):
        for col in bpy.data.collections:
            if hasattr(col, "asset_data") and col.asset_data:
                assets.append(col)

    if asset_type_filter == "ALL":
        for world in bpy.data.worlds:
            if hasattr(world, "asset_data") and world.asset_data:
                assets.append(world)
        for brush in bpy.data.brushes:
            if hasattr(brush, "asset_data") and brush.asset_data:
                assets.append(brush)

    return assets


def is_asset_marked(data_block, exclude_asset=None) -> bool:
    """Return True if *data_block* is marked as an asset (ignoring *exclude_asset*)."""
    if exclude_asset and data_block == exclude_asset:
        return False
    return hasattr(data_block, "asset_data") and data_block.asset_data is not None


# ---------------------------------------------------------------------------
# Slugification helpers
# ---------------------------------------------------------------------------

def _slugify(name: str) -> str:
    """Return a URL-friendly slug: lowercase, hyphens, no special chars."""
    slug = name.lower().replace(" ", "-").replace("_", "-")
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def _sku_from_name(name: str) -> str:
    """Generate an SKU like ``NO3D-TOOLS-DOJO-BRACKET``."""
    upper = name.upper().replace(" ", "-").replace("_", "-")
    upper = re.sub(r"[^A-Z0-9\-]", "", upper)
    upper = re.sub(r"-+", "-", upper).strip("-")
    return f"NO3D-TOOLS-{upper}"


# ---------------------------------------------------------------------------
# Auto-detect type tags
# ---------------------------------------------------------------------------

def _auto_type_tags(asset) -> list[str]:
    """Return tag strings inferred from the asset's Blender type."""
    type_name = type(asset).__name__
    tags: list[str] = []

    if type_name == "Object":
        tags.append("mesh-object")
        if hasattr(asset, "modifiers"):
            for mod in asset.modifiers:
                if mod.type == "NODES":
                    tags.append("geometry-nodes")
                    break

    elif type_name in ("NodeTree",):
        # Distinguish GeoNode vs Shader node trees
        bl_idname = getattr(asset, "bl_idname", "") or ""
        tree_type = getattr(asset, "type", "") or ""
        if "Geometry" in bl_idname or tree_type == "GeometryNodeTree":
            tags.append("geometry-nodes")
        elif "Shader" in bl_idname or tree_type == "ShaderNodeTree":
            tags.append("shader")
        else:
            tags.append("node-group")

    elif type_name == "Material":
        tags.append("material")
        tags.append("shader")

    elif type_name == "Collection":
        tags.append("collection")

    return tags


# ---------------------------------------------------------------------------
# Frontmatter generation (Phase 2)
# ---------------------------------------------------------------------------

def _yaml_quote(value: str) -> str:
    """Wrap *value* in double quotes, escaping inner double quotes."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _parse_existing_frontmatter(filepath: str) -> tuple[dict, str]:
    """Read *filepath* and split into (frontmatter_dict, markdown_body).

    Returns ``({}, "")`` if parsing fails or file does not exist.
    """
    if not os.path.isfile(filepath):
        return {}, ""

    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            content = fh.read()
    except OSError:
        return {}, ""

    if not content.startswith("---"):
        return {}, content

    # Find closing ---
    second = content.find("---", 3)
    if second == -1:
        return {}, content

    yaml_block = content[3:second].strip()
    body = content[second + 3:].lstrip("\n")

    fm: dict = {}
    current_key: str | None = None
    current_list: list[str] | None = None
    nested_dict: dict | None = None
    nested_key: str | None = None
    changelog_list: list[dict] | None = None
    changelog_entry: dict | None = None

    for raw_line in yaml_block.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue

        indent = len(raw_line) - len(raw_line.lstrip())

        # Top-level key: value
        if indent == 0 and ":" in stripped:
            # Flush any open list/dict
            if current_list is not None and current_key:
                fm[current_key] = current_list
                current_list = None
            if nested_dict is not None and nested_key:
                fm[nested_key] = nested_dict
                nested_dict = None
            if changelog_list is not None:
                if changelog_entry:
                    changelog_list.append(changelog_entry)
                    changelog_entry = None
                fm["changelog"] = changelog_list
                changelog_list = None

            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()
            current_key = key

            if not val:
                # Could be start of a list, dict, or changelog
                if key == "changelog":
                    changelog_list = []
                    changelog_entry = None
                    continue
                elif key == "metafields":
                    nested_dict = {}
                    nested_key = key
                    continue
                else:
                    current_list = []
                    continue

            # Scalar value — strip quotes
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            elif val.startswith("'") and val.endswith("'"):
                val = val[1:-1]
            fm[key] = val
            current_key = None
            continue

        # List item under current_key
        if current_list is not None and stripped.startswith("- "):
            item = stripped[2:].strip().strip('"').strip("'")
            current_list.append(item)
            continue

        # Nested dict items (metafields)
        if nested_dict is not None and ":" in stripped:
            k, _, v = stripped.partition(":")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            nested_dict[k] = v
            continue

        # Changelog entries
        if changelog_list is not None:
            if stripped.startswith("- version:"):
                if changelog_entry:
                    changelog_list.append(changelog_entry)
                changelog_entry = {}
                _, _, v = stripped.partition(":")
                changelog_entry["version"] = v.strip().strip('"').strip("'")
                continue
            if changelog_entry is not None and ":" in stripped:
                k, _, v = stripped.partition(":")
                changelog_entry[k.strip()] = v.strip().strip('"').strip("'")
                continue

    # Flush
    if current_list is not None and current_key:
        fm[current_key] = current_list
    if nested_dict is not None and nested_key:
        fm[nested_key] = nested_dict
    if changelog_list is not None:
        if changelog_entry:
            changelog_list.append(changelog_entry)
        fm["changelog"] = changelog_list

    return fm, body


def _read_legacy_json(json_path: str) -> dict:
    """Read a v1 ``{Name}.json`` and return a flat dict of useful fields."""
    try:
        with open(json_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Could not read legacy JSON %s: %s", json_path, exc)
        return {}

    result: dict = {}
    for key in ("title", "handle", "vendor", "product_type", "status", "description"):
        if key in data:
            result[key] = data[key]

    if "tags" in data and isinstance(data["tags"], list):
        result["tags"] = data["tags"]

    if "variants" in data and isinstance(data["variants"], list) and data["variants"]:
        variant = data["variants"][0]
        if "price" in variant:
            result["price"] = str(variant["price"])
        if "sku" in variant:
            result["sku"] = variant["sku"]

    return result


def _build_frontmatter_string(fm: dict) -> str:
    """Render *fm* dict as a YAML frontmatter block (no external deps)."""
    lines: list[str] = ["---"]

    def _scalar(key: str, value: str) -> None:
        lines.append(f"{key}: {_yaml_quote(value)}")

    _scalar("title", fm.get("title", ""))
    _scalar("handle", fm.get("handle", ""))
    _scalar("price", fm.get("price", "0.00"))
    _scalar("sku", fm.get("sku", ""))
    _scalar("status", fm.get("status", "draft"))
    _scalar("vendor", fm.get("vendor", "The Well Tarot"))
    _scalar("product_type", fm.get("product_type", "Blender Add-on"))

    # tags
    tags = fm.get("tags", [])
    if tags:
        lines.append("tags:")
        for tag in tags:
            lines.append(f"  - {_yaml_quote(tag)}")
    else:
        lines.append("tags: []")

    # metafields
    mf = fm.get("metafields", {})
    if mf:
        lines.append("metafields:")
        for k, v in mf.items():
            lines.append(f"  {k}: {_yaml_quote(str(v))}")

    # changelog
    changelog = fm.get("changelog", [])
    if changelog:
        lines.append("changelog:")
        for entry in changelog:
            lines.append(f"  - version: {_yaml_quote(entry.get('version', '1.0.0'))}")
            lines.append(f"    date: {_yaml_quote(entry.get('date', ''))}")
            lines.append(f"    description: {_yaml_quote(entry.get('description', ''))}")

    lines.append("---")
    return "\n".join(lines)


def generate_asset_frontmatter(asset, target_dir: str, prefs=None, overwrite: bool = False) -> str | None:
    """Write ``desc_{AssetName}.md`` with YAML frontmatter.

    * If ``{Name}.json`` exists in *target_dir*, seed from it.
    * If ``desc_{Name}.md`` already exists, update frontmatter but preserve
      the markdown body.

    Returns the written file path, or ``None`` on error.
    """
    asset_name = getattr(asset, "name", "asset")

    # Target folder is target_dir/asset_name
    asset_folder = os.path.join(target_dir, asset_name)
    os.makedirs(asset_folder, exist_ok=True)

    desc_path = os.path.join(asset_folder, f"desc_{asset_name}.md")
    json_path = os.path.join(asset_folder, f"{asset_name}.json")

    if os.path.isfile(desc_path) and not overwrite:
        log.info(
            "Skipping frontmatter overwrite for '%s' (existing file: %s)",
            asset_name,
            desc_path,
        )
        return desc_path

    # ------------------------------------------------------------------
    # Collect metadata from asset
    # ------------------------------------------------------------------
    asset_data = getattr(asset, "asset_data", None)
    blender_tags: list[str] = []
    if asset_data:
        blender_tags = [tag.name for tag in getattr(asset_data, "tags", [])]

    type_tags = _auto_type_tags(asset)
    all_tags = list(dict.fromkeys(["blender"] + type_tags + blender_tags))

    blender_version = f"{bpy.app.version[0]}.{bpy.app.version[1]}+"
    source_file = os.path.basename(bpy.data.filepath) if bpy.data.filepath else "unknown"
    today = datetime.now().strftime("%Y-%m-%d")
    asset_type_str = type(asset).__name__

    vendor = "The Well Tarot"
    product_type = "Blender Add-on"
    if prefs:
        vendor = getattr(prefs, "default_vendor", vendor) or vendor
        product_type = getattr(prefs, "default_product_type", product_type) or product_type

    # ------------------------------------------------------------------
    # Seed from legacy JSON if present
    # ------------------------------------------------------------------
    legacy = _read_legacy_json(json_path) if os.path.isfile(json_path) else {}

    # ------------------------------------------------------------------
    # Seed from existing frontmatter if present
    # ------------------------------------------------------------------
    existing_fm, existing_body = _parse_existing_frontmatter(desc_path)

    # ------------------------------------------------------------------
    # Merge: existing > legacy > auto-generated
    # ------------------------------------------------------------------
    def _pick(key: str, auto_value: str) -> str:
        if key in existing_fm and existing_fm[key]:
            return str(existing_fm[key])
        if key in legacy and legacy[key]:
            return str(legacy[key])
        return auto_value

    fm: dict = {
        "title": _pick("title", asset_name),
        "handle": _pick("handle", _slugify(asset_name)),
        "price": _pick("price", "0.00"),
        "sku": _pick("sku", _sku_from_name(asset_name)),
        "status": _pick("status", "draft"),
        "vendor": _pick("vendor", vendor),
        "product_type": _pick("product_type", product_type),
    }

    # Tags: merge existing + legacy + auto (deduplicated, order preserved)
    merged_tags = list(existing_fm.get("tags", []) or [])
    merged_tags += legacy.get("tags", []) or []
    merged_tags += all_tags
    fm["tags"] = list(dict.fromkeys(merged_tags))

    # Metafields: always update from current Blender state
    existing_mf = existing_fm.get("metafields", {}) if isinstance(existing_fm.get("metafields"), dict) else {}
    fm["metafields"] = {
        **existing_mf,
        "asset_type": asset_type_str,
        "blender_version": blender_version,
        "export_date": today,
        "source_file": source_file,
        "blend_file": f"{asset_name}.blend",
        "thumbnail": f"icon_{asset_name}.png",
    }

    # Changelog: preserve existing, add initial entry if empty
    existing_changelog = existing_fm.get("changelog", [])
    if isinstance(existing_changelog, list) and existing_changelog:
        fm["changelog"] = existing_changelog
    else:
        fm["changelog"] = [
            {"version": "1.0.0", "date": today, "description": "Initial export"},
        ]

    # ------------------------------------------------------------------
    # Build output
    # ------------------------------------------------------------------
    frontmatter_str = _build_frontmatter_string(fm)

    if existing_body.strip():
        body = existing_body
    else:
        body = f"\n# {asset_name}\n\n<!-- Description to be written in Obsidian -->\n"

    try:
        with open(desc_path, "w", encoding="utf-8") as fh:
            fh.write(frontmatter_str)
            fh.write("\n")
            fh.write(body)
        log.info("Wrote frontmatter to %s", desc_path)
        return desc_path
    except OSError as exc:
        log.error("Failed to write frontmatter for '%s': %s", asset_name, exc)
        return None


# ---------------------------------------------------------------------------
# Thumbnail export (retained from v1, cleaned up)
# ---------------------------------------------------------------------------

def export_asset_thumbnail(asset, target_dir: str, overwrite: bool = True) -> str | None:
    """Export asset thumbnail as a PNG to ``target_dir/{asset_name}/icon_{asset_name}.png``."""
    asset_name = getattr(asset, "name", "asset")
    asset_folder = os.path.join(target_dir, asset_name)
    os.makedirs(asset_folder, exist_ok=True)
    thumbnail_path = os.path.join(asset_folder, f"icon_{asset_name}.png")

    if os.path.isfile(thumbnail_path) and not overwrite:
        log.info(
            "Skipping thumbnail overwrite for '%s' (existing file: %s)",
            asset_name,
            thumbnail_path,
        )
        return thumbnail_path

    asset_data = getattr(asset, "asset_data", None)
    if not asset_data:
        log.warning("No asset_data for '%s' — skipping thumbnail", asset_name)
        return None

    preview = asset.preview
    if not preview or preview.image_size[0] == 0:
        log.warning("No preview image for '%s' — skipping thumbnail", asset_name)
        return None

    pixels = list(preview.image_pixels_float)
    if not pixels:
        log.warning("Preview has no pixel data for '%s'", asset_name)
        return None

    try:
        import array

        width, height = preview.image_size
        pixel_bytes = array.array("B")
        for i in range(0, len(pixels), 4):
            r = max(0, min(255, int(pixels[i] * 255)))
            g = max(0, min(255, int(pixels[i + 1] * 255)))
            b = max(0, min(255, int(pixels[i + 2] * 255)))
            a = max(0, min(255, int(pixels[i + 3] * 255)))
            pixel_bytes.extend([r, g, b, a])

        temp_image = bpy.data.images.new(
            name=f"_tmp_preview_{asset_name}",
            width=width,
            height=height,
            alpha=True,
        )
        temp_image.pixels = [p / 255.0 for p in pixel_bytes]
        temp_image.filepath_raw = thumbnail_path
        temp_image.file_format = "PNG"
        temp_image.save()
        bpy.data.images.remove(temp_image)

        log.info("Exported thumbnail for '%s' to %s", asset_name, thumbnail_path)
        return thumbnail_path

    except Exception as exc:
        log.error("Failed to export thumbnail for '%s': %s", asset_name, exc)
        return None


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def get_file_size(filepath: str) -> int:
    """Return file size in bytes, or 0 on error."""
    try:
        return os.path.getsize(filepath)
    except (OSError, FileNotFoundError):
        return 0


# ---------------------------------------------------------------------------
# Dependency scanning (retained from v1, cleaned up)
# ---------------------------------------------------------------------------

def isolate_material(material, asset_name: str):
    """Create an isolated duplicate of *material* (not marked as an asset)."""
    isolated_name = f"{material.name}_{asset_name}_isolated"
    if isolated_name in bpy.data.materials:
        return bpy.data.materials[isolated_name]

    isolated_mat = material.copy()
    isolated_mat.name = isolated_name
    if hasattr(material, "node_tree") and material.node_tree:
        isolated_mat.node_tree = material.node_tree.copy()

    log.info("Isolated material: %s -> %s", material.name, isolated_name)
    return isolated_mat


def isolate_node_group(node_group, asset_name: str):
    """Create an isolated duplicate of *node_group* (not marked as an asset)."""
    isolated_name = f"{asset_name}_isolated_{node_group.name}"
    if isolated_name in bpy.data.node_groups:
        isolated_ng = bpy.data.node_groups[isolated_name]
        if hasattr(isolated_ng, "asset_data") and isolated_ng.asset_data:
            isolated_ng.asset_data.clear()
        return isolated_ng

    isolated_ng = node_group.copy()
    isolated_ng.name = isolated_name
    if hasattr(isolated_ng, "asset_data") and isolated_ng.asset_data:
        isolated_ng.asset_data.clear()

    log.info("Isolated NodeGroup: %s -> %s", node_group.name, isolated_name)
    return isolated_ng


def scan_node_group_for_asset_dependencies(node_group, exclude_asset=None) -> list[dict]:
    """Recursively scan a NodeGroup for asset dependencies."""
    dependencies: list[dict] = []
    if not hasattr(node_group, "nodes"):
        return dependencies

    for node in node_group.nodes:
        if hasattr(node, "node_tree") and node.node_tree:
            referenced = node.node_tree
            if referenced and is_asset_marked(referenced, exclude_asset=exclude_asset):
                dependencies.append({
                    "dependency": referenced,
                    "type": "NodeGroup",
                    "relationship": "nested_node_group",
                    "node_name": node.name,
                    "severity": "warning",
                    "action_available": "isolate",
                })
                nested = scan_node_group_for_asset_dependencies(referenced, exclude_asset)
                dependencies.extend(nested)
    return dependencies


def scan_object_for_asset_dependencies(obj, exclude_asset=None) -> list[dict]:
    """Scan an object for asset dependencies."""
    dependencies: list[dict] = []

    if hasattr(obj, "modifiers"):
        for mod in obj.modifiers:
            if mod.type == "NODES" and hasattr(mod, "node_group") and mod.node_group:
                if is_asset_marked(mod.node_group, exclude_asset=exclude_asset):
                    dependencies.append({
                        "dependency": mod.node_group,
                        "type": "NodeGroup",
                        "relationship": "modifier_reference",
                        "modifier_name": mod.name,
                        "severity": "warning",
                        "action_available": "remove",
                    })

    if hasattr(obj, "data") and obj.data and hasattr(obj.data, "materials"):
        for mat in obj.data.materials:
            if mat and is_asset_marked(mat, exclude_asset=exclude_asset):
                dependencies.append({
                    "dependency": mat,
                    "type": "Material",
                    "relationship": "material_slot",
                    "severity": "warning",
                    "action_available": "isolate",
                })
            elif mat:
                deps = scan_material_for_asset_dependencies(mat, exclude_asset)
                dependencies.extend(deps)

    return dependencies


def scan_material_for_asset_dependencies(material, exclude_asset=None) -> list[dict]:
    """Scan a material's node tree for asset dependencies."""
    if hasattr(material, "node_tree") and material.node_tree:
        return scan_node_group_for_asset_dependencies(material.node_tree, exclude_asset)
    return []


def detect_asset_dependencies(asset) -> list[dict]:
    """Main entry point: scan *asset* for problematic dependencies."""
    asset_type = type(asset).__name__

    if asset_type == "Object":
        return scan_object_for_asset_dependencies(asset, exclude_asset=asset)
    if asset_type == "NodeGroup":
        return scan_node_group_for_asset_dependencies(asset, exclude_asset=asset)
    if asset_type == "Material":
        return scan_material_for_asset_dependencies(asset, exclude_asset=asset)
    if asset_type == "Collection":
        deps: list[dict] = []
        for obj in asset.objects:
            if not is_asset_marked(obj, exclude_asset=asset):
                deps.extend(scan_object_for_asset_dependencies(obj, exclude_asset=asset))
        return deps

    return []
