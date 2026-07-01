"""
No3d Asset Developer — Operators.

Export (active, all, thumbnails), dependency cleanup, dev notes, addon update.
"""

import glob
import logging
import os
import platform
import subprocess

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Operator

from . import utils
from . import blend_export
from . import extraction_methods
from . import wip_sync
from .notes import note_manager

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ASSET_TYPE_ITEMS = [
    ("ALL", "All Types", "Export all asset types"),
    ("OBJECT", "Objects", "Export object assets only"),
    ("MATERIAL", "Materials", "Export material assets only"),
    ("COLLECTION", "Collections", "Export collection assets only"),
    ("NODE_TREE", "Node Groups", "Export node group assets only"),
]


def get_catalog_items(self, context):
    """Dynamic enum callback for catalog selection."""
    try:
        catalogs = utils.get_available_catalogs()
        items = [("ALL_CATALOGS", "All Catalogs",
                  "Export assets from all catalogs (excluding unassigned)")]
        items.extend(
            [(c, c, f"Export assets from {c} catalog") for c in catalogs]
        )
        return items
    except Exception as exc:
        log.warning("Could not retrieve catalogs: %s", exc)
        return [("ALL_CATALOGS", "All Catalogs",
                 "Export assets from all catalogs (excluding unassigned)")]


# ---------------------------------------------------------------------------
# Helper: resolve addon preferences
# ---------------------------------------------------------------------------

def _get_prefs():
    """Return the addon's AddonPreferences instance, or None."""
    addon_name = __name__.rpartition(".")[0]  # package name
    return bpy.context.preferences.addons.get(addon_name, None)


def _get_prefs_obj():
    entry = _get_prefs()
    if entry and hasattr(entry, "preferences"):
        return entry.preferences
    return None


# ---------------------------------------------------------------------------
# Helper: active asset from context
# ---------------------------------------------------------------------------

def _get_active_asset(context):
    """Return the active asset data-block from the Asset Browser or 3-D
    Viewport, or ``None``."""
    if hasattr(context, "id") and context.id:
        candidate = context.id
        if hasattr(candidate, "asset_data") and candidate.asset_data:
            return candidate
    if hasattr(context, "active_object") and context.active_object:
        obj = context.active_object
        if hasattr(obj, "asset_data") and obj.asset_data:
            return obj
    if hasattr(context, "selected_objects"):
        for obj in context.selected_objects:
            if hasattr(obj, "asset_data") and obj.asset_data:
                return obj
    return None


# ---------------------------------------------------------------------------
# Helper: per-asset export pipeline
# ---------------------------------------------------------------------------

def _export_single_asset(
    asset,
    directory: str,
    prefs,
    export_blend: bool = True,
    export_thumbnail: bool = True,
    export_frontmatter: bool = True,
    overwrite_blend: bool = True,
    overwrite_thumbnail: bool = True,
    overwrite_frontmatter: bool = False,
    overwrite_notes: bool = False,
):
    """Run the full export pipeline for one asset.  Returns a list of error
    strings (empty on success)."""
    errors: list[str] = []
    asset_name = getattr(asset, "name", "unknown")
    asset_folder = os.path.join(directory, asset_name)
    os.makedirs(asset_folder, exist_ok=True)

    # --- .blend export ---
    if export_blend:
        source = bpy.data.filepath
        if not source:
            errors.append(f"'{asset_name}': current file must be saved before exporting .blend")
        else:
            output_path = os.path.join(asset_folder, f"{asset_name}.blend")
            if os.path.isfile(output_path) and not overwrite_blend:
                log.info(
                    "Skipping .blend overwrite for '%s' (existing file: %s)",
                    asset_name,
                    output_path,
                )
            else:
                ok, size, err = blend_export.export_asset_blend(asset, source, output_path)
                if not ok:
                    errors.append(f"'{asset_name}' .blend export failed: {err}")

    # --- Frontmatter ---
    if export_frontmatter:
        result = utils.generate_asset_frontmatter(
            asset,
            directory,
            prefs,
            overwrite=overwrite_frontmatter,
        )
        if result is None:
            errors.append(f"'{asset_name}': frontmatter generation failed")

    # --- Thumbnail ---
    if export_thumbnail:
        result = utils.export_asset_thumbnail(
            asset,
            directory,
            overwrite=overwrite_thumbnail,
        )
        if result is None:
            log.info("No thumbnail exported for '%s' (preview may be unavailable)", asset_name)

    # --- Notes ---
    if note_manager.has_notes(asset_name):
        note_manager.export_notes(asset_name, asset_folder, overwrite=overwrite_notes)

    return errors


# ===================================================================
# Export Active Asset
# ===================================================================

class NO3D_OT_export_active_asset(Operator):
    """Export the single active asset from the Asset Browser"""
    bl_idname = "asset.export_active_no3d"
    bl_label = "Export Active Asset"
    bl_description = (
        "Export the active asset as an individual .blend with frontmatter, "
        "thumbnail, and dev notes"
    )
    bl_options = {"REGISTER", "UNDO"}

    directory: StringProperty(
        name="Export Directory",
        description="Directory to export asset to",
        subtype="DIR_PATH",
        default="",
    )

    overwrite_blend: BoolProperty(
        name="Overwrite .blend",
        description="Overwrite existing {AssetName}.blend files",
        default=True,
    )

    overwrite_thumbnail: BoolProperty(
        name="Overwrite Icon",
        description="Overwrite existing icon_{AssetName}.png files",
        default=True,
    )

    overwrite_frontmatter: BoolProperty(
        name="Overwrite Frontmatter (.md)",
        description="Overwrite existing desc_{AssetName}.md files",
        default=False,
    )

    overwrite_notes: BoolProperty(
        name="Overwrite Notes (.md)",
        description="Overwrite existing notes_{AssetName}.md files",
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text="Overwrite Existing Files:")
        box.prop(self, "overwrite_blend")
        box.prop(self, "overwrite_thumbnail")
        box.prop(self, "overwrite_frontmatter")
        box.prop(self, "overwrite_notes")

    def invoke(self, context, event):
        # Pre-fill from preferences if available
        prefs = _get_prefs_obj()
        if prefs and prefs.export_library_path:
            self.directory = prefs.export_library_path
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        if not self.directory:
            self.report({"ERROR"}, "No directory selected")
            return {"CANCELLED"}

        asset = _get_active_asset(context)
        if not asset:
            self.report({"ERROR"}, "No active asset. Select an asset in the Asset Browser.")
            return {"CANCELLED"}

        prefs = _get_prefs_obj()
        errors = _export_single_asset(
            asset,
            self.directory,
            prefs,
            overwrite_blend=self.overwrite_blend,
            overwrite_thumbnail=self.overwrite_thumbnail,
            overwrite_frontmatter=self.overwrite_frontmatter,
            overwrite_notes=self.overwrite_notes,
        )

        if errors:
            for e in errors:
                log.error(e)
            self.report({"WARNING"}, f"Export completed with errors: {'; '.join(errors)}")
        else:
            self.report({"INFO"}, f"Exported '{asset.name}' successfully")

        return {"FINISHED"}


# ===================================================================
# Export All Assets
# ===================================================================

class NO3D_OT_export_all_assets(Operator):
    """Export all visible assets with frontmatter and thumbnails"""
    bl_idname = "asset.export_all_no3d"
    bl_label = "Export All Assets"
    bl_description = (
        "Export all assets from the current .blend file as individual "
        ".blend files with frontmatter metadata and thumbnails"
    )
    bl_options = {"REGISTER", "UNDO"}

    directory: StringProperty(
        name="Export Directory",
        description="Directory to export assets to",
        subtype="DIR_PATH",
        default="",
    )

    asset_type_filter: EnumProperty(
        name="Asset Type",
        description="Filter which asset types to export",
        items=ASSET_TYPE_ITEMS,
        default="ALL",
    )

    catalog_filter: EnumProperty(
        name="Catalog",
        description="Select which catalog to export from",
        items=get_catalog_items,
        default=0,
        options=set(),
    )

    export_thumbnail: BoolProperty(
        name="Export Thumbnails",
        description="Export PNG thumbnails for each asset",
        default=True,
    )

    export_frontmatter: BoolProperty(
        name="Export Frontmatter",
        description="Generate desc_{Name}.md frontmatter files",
        default=True,
    )

    overwrite_blend: BoolProperty(
        name="Overwrite .blend",
        description="Overwrite existing {AssetName}.blend files",
        default=True,
    )

    overwrite_thumbnail: BoolProperty(
        name="Overwrite Icon",
        description="Overwrite existing icon_{AssetName}.png files",
        default=True,
    )

    overwrite_frontmatter: BoolProperty(
        name="Overwrite Frontmatter (.md)",
        description="Overwrite existing desc_{AssetName}.md files",
        default=False,
    )

    overwrite_notes: BoolProperty(
        name="Overwrite Notes (.md)",
        description="Overwrite existing notes_{AssetName}.md files",
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "asset_type_filter")
        layout.prop(self, "catalog_filter")
        layout.prop(self, "export_thumbnail")
        layout.prop(self, "export_frontmatter")
        box = layout.box()
        box.label(text="Overwrite Existing Files:")
        box.prop(self, "overwrite_blend")
        icon_row = box.row()
        icon_row.enabled = self.export_thumbnail
        icon_row.prop(self, "overwrite_thumbnail")
        frontmatter_row = box.row()
        frontmatter_row.enabled = self.export_frontmatter
        frontmatter_row.prop(self, "overwrite_frontmatter")
        box.prop(self, "overwrite_notes")

    def invoke(self, context, event):
        prefs = _get_prefs_obj()
        if prefs and prefs.export_library_path:
            self.directory = prefs.export_library_path
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        if not self.directory:
            self.report({"ERROR"}, "No directory selected")
            return {"CANCELLED"}

        # Resolve catalog filter
        catalog_filter = getattr(self, "catalog_filter", 0)
        try:
            catalog_items = get_catalog_items(self, context)
            if isinstance(catalog_filter, int) and catalog_filter < len(catalog_items):
                catalog_value = catalog_items[catalog_filter][0]
            else:
                catalog_value = "ALL_CATALOGS"
        except Exception:
            catalog_value = "ALL_CATALOGS"

        if catalog_value == "ALL_CATALOGS":
            all_assets = utils.get_all_visible_assets(context, self.asset_type_filter)
        else:
            all_assets = utils.get_assets_by_catalog(catalog_value, self.asset_type_filter)

        if not all_assets:
            self.report(
                {"ERROR"},
                "No assets found. Mark objects/materials as assets first "
                "(Right-click > Mark as Asset).",
            )
            return {"CANCELLED"}

        os.makedirs(self.directory, exist_ok=True)

        wm = context.window_manager
        wm.progress_begin(0, len(all_assets))

        prefs = _get_prefs_obj()
        exported_count = 0
        all_errors: list[str] = []
        notes_count = 0

        for i, asset in enumerate(all_assets):
            wm.progress_update(i)
            errs = _export_single_asset(
                asset,
                self.directory,
                prefs,
                export_thumbnail=self.export_thumbnail,
                export_frontmatter=self.export_frontmatter,
                overwrite_blend=self.overwrite_blend,
                overwrite_thumbnail=self.overwrite_thumbnail,
                overwrite_frontmatter=self.overwrite_frontmatter,
                overwrite_notes=self.overwrite_notes,
            )
            if errs:
                all_errors.extend(errs)
            else:
                exported_count += 1
            if note_manager.has_notes(asset.name):
                notes_count += 1

        wm.progress_end()

        summary = f"Exported {exported_count} asset(s) to {self.directory}"
        if notes_count:
            summary += f" ({notes_count} with notes)"
        if all_errors:
            for e in all_errors:
                log.error(e)
            self.report({"WARNING"}, f"{summary} — {len(all_errors)} error(s)")
        else:
            self.report({"INFO"}, summary)

        return {"FINISHED"}


# ===================================================================
# Export Thumbnails Only
# ===================================================================

class NO3D_OT_export_thumbnails_only(Operator):
    """Export only thumbnail images for all assets"""
    bl_idname = "asset.export_thumbnails_only_no3d"
    bl_label = "Export Thumbnails Only"
    bl_description = "Export only thumbnail/icon images for all assets"
    bl_options = {"REGISTER", "UNDO"}

    directory: StringProperty(
        name="Export Directory",
        description="Directory to export thumbnails to",
        subtype="DIR_PATH",
        default="",
    )

    asset_type_filter: EnumProperty(
        name="Asset Type",
        description="Filter which asset types to export",
        items=ASSET_TYPE_ITEMS,
        default="ALL",
    )

    catalog_filter: EnumProperty(
        name="Catalog",
        description="Select which catalog to export from",
        items=get_catalog_items,
        default=0,
        options=set(),
    )

    overwrite_thumbnail: BoolProperty(
        name="Overwrite Icon",
        description="Overwrite existing icon_{AssetName}.png files",
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "asset_type_filter")
        layout.prop(self, "catalog_filter")
        layout.prop(self, "overwrite_thumbnail")

    def invoke(self, context, event):
        prefs = _get_prefs_obj()
        if prefs and prefs.export_library_path:
            self.directory = prefs.export_library_path
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        if not self.directory:
            self.report({"ERROR"}, "No directory selected")
            return {"CANCELLED"}

        catalog_filter = getattr(self, "catalog_filter", 0)
        try:
            catalog_items = get_catalog_items(self, context)
            if isinstance(catalog_filter, int) and catalog_filter < len(catalog_items):
                catalog_value = catalog_items[catalog_filter][0]
            else:
                catalog_value = "ALL_CATALOGS"
        except Exception:
            catalog_value = "ALL_CATALOGS"

        if catalog_value == "ALL_CATALOGS":
            all_assets = utils.get_all_visible_assets(context, self.asset_type_filter)
        else:
            all_assets = utils.get_assets_by_catalog(catalog_value, self.asset_type_filter)

        if not all_assets:
            self.report({"ERROR"}, "No assets found in current .blend file")
            return {"CANCELLED"}

        os.makedirs(self.directory, exist_ok=True)
        wm = context.window_manager
        wm.progress_begin(0, len(all_assets))

        exported = 0
        errors: list[str] = []

        for i, asset in enumerate(all_assets):
            wm.progress_update(i)
            try:
                path = utils.export_asset_thumbnail(
                    asset,
                    self.directory,
                    overwrite=self.overwrite_thumbnail,
                )
                if path:
                    exported += 1
            except Exception as exc:
                errors.append(f"Thumbnail for '{getattr(asset, 'name', '?')}': {exc}")

        wm.progress_end()

        if errors:
            for e in errors:
                log.error(e)
            self.report({"WARNING"}, f"Exported {exported} thumbnails with {len(errors)} error(s)")
        else:
            self.report({"INFO"}, f"Exported {exported} thumbnails")

        return {"FINISHED"}


# ===================================================================
# Update Addon
# ===================================================================

class NO3D_OT_update_addon(Operator):
    """Update the No3d Asset Developer add-on"""
    bl_idname = "preferences.addon_update_no3d"
    bl_label = "Update Add-on"
    bl_description = "Install a fresh update of the No3d Asset Developer add-on"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(
        name="Update File",
        description="Path to the add-on zip file to install",
        subtype="FILE_PATH",
        default="",
    )

    def invoke(self, context, event):
        default_path = os.path.expanduser(
            "~/Library/CloudStorage/Dropbox/Caveman Creative/"
            "THE WELL_Digital Assets/The Well Code/solvet-global"
        )
        if os.path.exists(default_path):
            zip_files = glob.glob(os.path.join(default_path, "No3d_Asset_Developer_v*.zip"))
            if not zip_files:
                zip_files = glob.glob(os.path.join(default_path, "NO3D_Tools_Asset_Utility_v*.zip"))
            if zip_files:
                self.filepath = max(zip_files, key=os.path.getmtime)

        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        if not self.filepath:
            self.report({"ERROR"}, "No update file selected")
            return {"CANCELLED"}

        if not os.path.exists(self.filepath):
            self.report({"ERROR"}, f"File not found: {self.filepath}")
            return {"CANCELLED"}

        if not self.filepath.endswith(".zip"):
            self.report({"ERROR"}, "Please select a .zip file")
            return {"CANCELLED"}

        try:
            addon_name = "no3d_asset_developer"
            if addon_name in bpy.context.preferences.addons:
                bpy.ops.preferences.addon_disable(module=addon_name)
            bpy.ops.preferences.addon_install(filepath=self.filepath, overwrite=True)
            bpy.ops.preferences.addon_enable(module=addon_name)
            bpy.ops.wm.save_userpref()
            self.report({"INFO"}, "Add-on updated. Restart Blender for full effect.")
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Update failed: {exc}")
            return {"CANCELLED"}


# ===================================================================
# Open Asset Location
# ===================================================================

class NO3D_OT_open_asset_location(Operator):
    """Open the asset's file location in Finder/Explorer"""
    bl_idname = "asset.open_location_no3d"
    bl_label = "Open Asset Location"
    bl_description = "Open the asset's file location in the system file manager"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        asset = _get_active_asset(context)
        if not asset:
            self.report({"WARNING"}, "No asset selected")
            return {"CANCELLED"}

        # Determine directory
        file_directory = None

        if hasattr(asset, "library") and asset.library:
            lib_path = getattr(asset.library, "filepath", "")
            if lib_path:
                if not os.path.isabs(lib_path):
                    base = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else None
                    if base:
                        lib_path = os.path.normpath(os.path.join(base, lib_path))
                    else:
                        lib_path = os.path.abspath(lib_path)
                else:
                    lib_path = os.path.normpath(lib_path)
                if os.path.exists(lib_path):
                    file_directory = os.path.dirname(lib_path)

        if not file_directory and bpy.data.filepath:
            file_directory = os.path.dirname(bpy.data.filepath)

        if not file_directory or not os.path.exists(file_directory):
            self.report({"ERROR"}, "Could not determine asset file location.")
            return {"CANCELLED"}

        try:
            system = platform.system()
            if system == "Darwin":
                subprocess.run(["open", file_directory])
            elif system == "Windows":
                os.startfile(file_directory)
            else:
                subprocess.run(["xdg-open", file_directory])
            self.report({"INFO"}, f"Opened: {file_directory}")
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to open location: {exc}")
            return {"CANCELLED"}


# ===================================================================
# Dependency scanning & cleanup (retained from v1)
# ===================================================================

class NO3D_OT_scan_asset_dependencies(Operator):
    """Scan the selected asset for problematic dependencies"""
    bl_idname = "asset.scan_dependencies_no3d"
    bl_label = "Scan Dependencies"
    bl_description = "Scan the selected asset for dependencies on other assets"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        asset = _get_active_asset(context)
        if not asset:
            self.report({"WARNING"}, "No asset selected.")
            return {"CANCELLED"}

        dependencies = utils.detect_asset_dependencies(asset)

        wm = context.window_manager
        dep_list = []
        for dep in dependencies:
            dep_list.append({
                "dependency_name": dep["dependency"].name,
                "dependency_type": type(dep["dependency"]).__name__,
                "type": dep["type"],
                "relationship": dep["relationship"],
                "severity": dep["severity"],
                "action_available": dep["action_available"],
                "node_name": dep.get("node_name", ""),
                "modifier_name": dep.get("modifier_name", ""),
            })

        wm["no3d_asset_dependencies"] = dep_list
        wm["no3d_scanned_asset_name"] = asset.name
        wm["no3d_scanned_asset_type"] = type(asset).__name__

        if dependencies:
            self.report({"INFO"}, f"Found {len(dependencies)} dependency issue(s)")
        else:
            self.report({"INFO"}, "No problematic dependencies found")

        return {"FINISHED"}


class NO3D_OT_isolate_node_group_dependency(Operator):
    """Isolate a NodeGroup dependency by creating a non-asset copy"""
    bl_idname = "asset.isolate_node_group_no3d"
    bl_label = "Isolate NodeGroup"
    bl_description = "Create an isolated copy of this NodeGroup dependency"
    bl_options = {"REGISTER", "UNDO"}

    dependency_name: StringProperty(name="Dependency Name")
    dependency_type: StringProperty(name="Dependency Type")
    node_name: StringProperty(name="Node Name", default="")
    modifier_name: StringProperty(name="Modifier Name", default="")

    def execute(self, context):
        asset = _get_active_asset(context)
        if not asset:
            self.report({"ERROR"}, "No asset selected.")
            return {"CANCELLED"}

        dependency = None
        if self.dependency_type == "NodeGroup" and self.dependency_name in bpy.data.node_groups:
            dependency = bpy.data.node_groups[self.dependency_name]

        if not dependency:
            self.report({"ERROR"}, f"Dependency '{self.dependency_name}' not found")
            return {"CANCELLED"}

        isolated_ng = utils.isolate_node_group(dependency, asset.name)
        asset_type = type(asset).__name__

        if asset_type == "NodeGroup" and hasattr(asset, "nodes"):
            for node in asset.nodes:
                if hasattr(node, "node_tree") and node.node_tree == dependency:
                    node.node_tree = isolated_ng
                    self.report({"INFO"}, f"Isolated NodeGroup in node '{node.name}'")
                    break
        elif asset_type == "Object" and self.modifier_name and hasattr(asset, "modifiers"):
            for mod in asset.modifiers:
                if mod.name == self.modifier_name and mod.type == "NODES":
                    if hasattr(mod, "node_group") and mod.node_group == dependency:
                        mod.node_group = isolated_ng
                        self.report({"INFO"}, f"Isolated NodeGroup in modifier '{mod.name}'")
                        break

        bpy.ops.asset.scan_dependencies_no3d()
        return {"FINISHED"}


class NO3D_OT_remove_dependency(Operator):
    """Remove or break a dependency reference"""
    bl_idname = "asset.remove_dependency_no3d"
    bl_label = "Remove Dependency"
    bl_description = "Remove or break this dependency reference"
    bl_options = {"REGISTER", "UNDO"}

    dependency_name: StringProperty(name="Dependency Name")
    dependency_type: StringProperty(name="Dependency Type")
    relationship: StringProperty(name="Relationship")
    modifier_name: StringProperty(name="Modifier Name", default="")

    def execute(self, context):
        asset = _get_active_asset(context)
        if not asset:
            self.report({"ERROR"}, "No asset selected.")
            return {"CANCELLED"}

        asset_type = type(asset).__name__

        if self.relationship == "modifier_reference" and self.modifier_name:
            if hasattr(asset, "modifiers"):
                for mod in asset.modifiers:
                    if mod.name == self.modifier_name:
                        asset.modifiers.remove(mod)
                        self.report({"INFO"}, f"Removed modifier '{self.modifier_name}'")
                        break
        elif self.relationship == "nested_node_group":
            if asset_type == "NodeGroup" and hasattr(asset, "nodes"):
                for node in asset.nodes:
                    if hasattr(node, "node_tree") and node.node_tree:
                        if node.node_tree.name == self.dependency_name:
                            node.node_tree = None
                            self.report({"INFO"}, f"Broke NodeGroup reference in '{node.name}'")
                            break

        bpy.ops.asset.scan_dependencies_no3d()
        return {"FINISHED"}


class NO3D_OT_clean_all_dependencies(Operator):
    """Automatically clean all detected dependencies"""
    bl_idname = "asset.clean_all_dependencies_no3d"
    bl_label = "Clean All Dependencies"
    bl_description = "Automatically resolve all detected dependency issues"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        asset = _get_active_asset(context)
        if not asset:
            self.report({"ERROR"}, "No asset selected.")
            return {"CANCELLED"}

        dependencies = utils.detect_asset_dependencies(asset)
        if not dependencies:
            self.report({"INFO"}, "No dependencies to clean")
            return {"FINISHED"}

        cleaned = 0
        for dep in dependencies:
            action = dep["action_available"]
            relationship = dep["relationship"]

            if dep["type"] == "NodeGroup" and action == "isolate":
                dependency = dep["dependency"]
                isolated_ng = utils.isolate_node_group(dependency, asset.name)
                asset_type = type(asset).__name__

                if asset_type == "NodeGroup" and hasattr(asset, "nodes"):
                    for node in asset.nodes:
                        if hasattr(node, "node_tree") and node.node_tree == dependency:
                            node.node_tree = isolated_ng
                            cleaned += 1
                            break
                elif relationship == "modifier_reference" and hasattr(asset, "modifiers"):
                    mod_name = dep.get("modifier_name", "")
                    for mod in asset.modifiers:
                        if mod.name == mod_name and mod.type == "NODES":
                            if hasattr(mod, "node_group") and mod.node_group == dependency:
                                mod.node_group = isolated_ng
                                cleaned += 1
                                break

            elif action == "remove" and relationship == "modifier_reference":
                if hasattr(asset, "modifiers"):
                    mod_name = dep.get("modifier_name", "")
                    for mod in asset.modifiers:
                        if mod.name == mod_name:
                            asset.modifiers.remove(mod)
                            cleaned += 1
                            break

        bpy.ops.asset.scan_dependencies_no3d()
        self.report({"INFO"}, f"Cleaned {cleaned} dependency issue(s)")
        return {"FINISHED"}


# ===================================================================
# v3.0 — Method-selectable extraction (Method A / Method B)
# ===================================================================

def _run_v3_extraction(asset, directory: str, method: str, prefs) -> tuple[list[str], list[str]]:
    """Run the chosen extraction method for one asset.

    Reuses utils.export_asset_thumbnail + frontmatter + notes after the .blend
    is written, so Method B benefits from the same metadata pipeline.
    Returns (errors, warnings).
    """
    errors: list[str] = []
    warnings: list[str] = []
    asset_name = getattr(asset, "name", "unknown")
    asset_folder = os.path.join(directory, asset_name)
    os.makedirs(asset_folder, exist_ok=True)
    output_path = os.path.join(asset_folder, f"{asset_name}.blend")

    source = bpy.data.filepath
    if method == "TEMPLATE_APPEND" and not source:
        errors.append(f"'{asset_name}': current file must be saved before Method A export")
        return errors, warnings

    ok, size, err, warns = extraction_methods.extract(method, asset, source, output_path)
    warnings.extend(warns)
    if not ok:
        errors.append(f"'{asset_name}' extraction failed ({method}): {err}")
        return errors, warnings

    # Thumbnail, frontmatter, notes — same pipeline as v2
    try:
        utils.export_asset_thumbnail(asset, directory, overwrite=True)
    except Exception as exc:
        warnings.append(f"thumbnail: {exc}")
    try:
        utils.generate_asset_frontmatter(asset, directory, prefs, overwrite=False)
    except Exception as exc:
        warnings.append(f"frontmatter: {exc}")
    if note_manager.has_notes(asset_name):
        note_manager.export_notes(asset_name, asset_folder, overwrite=False)

    return errors, warnings


class NO3D_OT_extract_v3_active(Operator):
    """v3.0: Extract the active asset using the method selected in the N-panel."""
    bl_idname = "asset.extract_v3_active_no3d"
    bl_label = "Extract Active Asset (v3)"
    bl_description = "Extract the active asset via the method chosen in the No3D Dev N-panel"
    bl_options = {"REGISTER", "UNDO"}

    directory: StringProperty(
        name="Export Directory",
        subtype="DIR_PATH",
        default="",
    )

    def invoke(self, context, event):
        prefs = _get_prefs_obj()
        if prefs and prefs.export_library_path:
            self.directory = prefs.export_library_path
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        if not self.directory:
            self.report({"ERROR"}, "No directory selected")
            return {"CANCELLED"}
        asset = _get_active_asset(context)
        if not asset:
            self.report({"ERROR"}, "No active asset. Select an asset in the Asset Browser.")
            return {"CANCELLED"}

        method = context.window_manager.no3d_extraction_method
        prefs = _get_prefs_obj()
        errors, warnings = _run_v3_extraction(asset, self.directory, method, prefs)

        if errors:
            for e in errors:
                log.error(e)
            self.report({"ERROR"}, "; ".join(errors))
            return {"CANCELLED"}

        msg = f"Exported '{asset.name}'"
        if warnings:
            msg += f" — {len(warnings)} warning(s): {warnings[0]}"
        self.report({"WARNING" if warnings else "INFO"}, msg)
        return {"FINISHED"}


class NO3D_OT_extract_v3_all(Operator):
    """v3.0: Extract all visible assets using the selected method."""
    bl_idname = "asset.extract_v3_all_no3d"
    bl_label = "Extract All Assets (v3)"
    bl_description = "Extract all marked assets using the method chosen in the No3D Dev N-panel"
    bl_options = {"REGISTER", "UNDO"}

    directory: StringProperty(
        name="Export Directory",
        subtype="DIR_PATH",
        default="",
    )

    def invoke(self, context, event):
        prefs = _get_prefs_obj()
        if prefs and prefs.export_library_path:
            self.directory = prefs.export_library_path
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        if not self.directory:
            self.report({"ERROR"}, "No directory selected")
            return {"CANCELLED"}

        assets = utils.get_all_visible_assets(context, "ALL")
        if not assets:
            self.report({"ERROR"}, "No assets found. Mark objects/materials as assets first.")
            return {"CANCELLED"}

        method = context.window_manager.no3d_extraction_method
        prefs = _get_prefs_obj()

        wm = context.window_manager
        wm.progress_begin(0, len(assets))
        exported = 0
        all_errors: list[str] = []
        all_warnings: list[str] = []

        for i, asset in enumerate(assets):
            wm.progress_update(i)
            errs, warns = _run_v3_extraction(asset, self.directory, method, prefs)
            if errs:
                all_errors.extend(errs)
            else:
                exported += 1
            all_warnings.extend(warns)

        wm.progress_end()
        summary = f"Exported {exported}/{len(assets)} asset(s)"
        if all_warnings:
            summary += f" — {len(all_warnings)} warning(s)"
        if all_errors:
            for e in all_errors:
                log.error(e)
            self.report({"WARNING"}, f"{summary} — {len(all_errors)} error(s)")
        else:
            self.report({"INFO"}, summary)
        return {"FINISHED"}


# ===================================================================
# Dev Notes operators (Phase 3)
# ===================================================================

class NO3D_OT_add_dev_note(Operator):
    """Add a timestamped developer note for the active asset"""
    bl_idname = "no3d.add_dev_note"
    bl_label = "Add Note"
    bl_description = "Add a quick dev note tagged to the active asset"
    bl_options = {"REGISTER"}

    def execute(self, context):
        wm = context.window_manager
        note_input = wm.no3d_note_input
        text = note_input.text.strip()
        if not text:
            self.report({"WARNING"}, "Note is empty")
            return {"CANCELLED"}

        # Determine asset context
        asset = _get_active_asset(context)
        asset_name = asset.name if asset else "Global"

        note_manager.add_note(asset_name, text)
        note_input.text = ""
        self.report({"INFO"}, f"Note added for '{asset_name}'")
        return {"FINISHED"}


class NO3D_OT_clear_dev_notes(Operator):
    """Clear all developer notes for the active asset"""
    bl_idname = "no3d.clear_dev_notes"
    bl_label = "Clear Notes"
    bl_description = "Clear all session notes for the active asset"
    bl_options = {"REGISTER"}

    def execute(self, context):
        asset = _get_active_asset(context)
        asset_name = asset.name if asset else "Global"
        note_manager.clear_notes(asset_name)
        self.report({"INFO"}, f"Cleared notes for '{asset_name}'")
        return {"FINISHED"}


# ===================================================================
# WIP Sync (auto-extract to WIP folder)
# ===================================================================

class NO3D_OT_open_wip_folder(Operator):
    """Open a specific folder inside the WIP directory in Finder/Explorer."""
    bl_idname = "asset.open_wip_folder_no3d"
    bl_label = "Open WIP Folder"
    bl_description = "Open this asset's WIP folder in the system file manager"
    bl_options = {"REGISTER"}

    folder_name: StringProperty(name="Folder Name", default="")

    def execute(self, context):
        wip = wip_sync.get_wip_folder()
        if not wip:
            self.report({"ERROR"}, "WIP folder not set")
            return {"CANCELLED"}
        target = os.path.join(wip, self.folder_name) if self.folder_name else wip
        if not os.path.isdir(target):
            self.report({"ERROR"}, f"Not a directory: {target}")
            return {"CANCELLED"}
        try:
            system = platform.system()
            if system == "Darwin":
                subprocess.run(["open", target])
            elif system == "Windows":
                os.startfile(target)
            else:
                subprocess.run(["xdg-open", target])
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to open: {exc}")
            return {"CANCELLED"}


class NO3D_OT_sync_wip_all(Operator):
    """Sync every marked asset in this file to the WIP folder."""
    bl_idname = "asset.sync_wip_all_no3d"
    bl_label = "Sync All Assets to WIP"
    bl_description = (
        "Extract every marked asset to {WIP folder}/{AssetName}/. "
        "Always overwrites .blend and thumbnail; preserves frontmatter and notes."
    )
    bl_options = {"REGISTER"}

    def execute(self, context):
        if not wip_sync.get_wip_folder():
            self.report({"ERROR"}, "Set the WIP Folder in the No3D Dev N-panel first")
            return {"CANCELLED"}

        ok, fail, errors = wip_sync.sync_all()
        if fail:
            for e in errors:
                log.error(e)
            self.report({"WARNING"}, f"Synced {ok}, {fail} failed (see console)")
        else:
            self.report({"INFO"}, f"Synced {ok} asset(s) to WIP folder")
        return {"FINISHED"}


# ===================================================================
# Registration
# ===================================================================

_classes = (
    NO3D_OT_export_active_asset,
    NO3D_OT_export_all_assets,
    NO3D_OT_export_thumbnails_only,
    NO3D_OT_open_asset_location,
    NO3D_OT_update_addon,
    NO3D_OT_scan_asset_dependencies,
    NO3D_OT_isolate_node_group_dependency,
    NO3D_OT_remove_dependency,
    NO3D_OT_clean_all_dependencies,
    NO3D_OT_extract_v3_active,
    NO3D_OT_extract_v3_all,
    NO3D_OT_open_wip_folder,
    NO3D_OT_sync_wip_all,
    NO3D_OT_add_dev_note,
    NO3D_OT_clear_dev_notes,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
