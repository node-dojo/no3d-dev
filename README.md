# No3d Asset Developer

A Blender add-on for turning marked assets into clean, individually-packaged
`.blend` files with metadata, thumbnails, and dev notes — built for maintaining
a distributable asset library.

- **Version:** 3.0.0
- **Blender:** 5.0+
- **License:** GPL-3.0-or-later
- **Location:** Asset Browser context menu · 3D Viewport → N-Panel → *No3D Dev*

## What it does

Marks, extracts, and exports individual assets from the current `.blend` into
their own self-contained files, each in a named folder alongside a JSON
metadata sidecar, a PNG thumbnail, and a description text file — ready to sync
to a storefront or asset library.

### Two export pipelines

- **Method A — Template Append (subprocess).** Opens a headless Blender on
  `_export_template.blend`, appends the asset, strips internal markings,
  purges orphans, and saves. Preserves Scene and METRIC/mm units. Default for
  production output.
- **Method B — Datablock Write (in-process).** `bpy.data.libraries.write()` of
  the asset and its dependencies. No subprocess, no template — faster, and
  pose-library-native. Output carries no Scene/units.

### WIP folder auto-sync

Point the add-on at a working folder and assets are auto-extracted as you work:

- **On Mark** — a newly marked asset is extracted immediately
- **On Save** — assets whose source changed are re-extracted
- **On Rename** — the asset's WIP subfolder is renamed to match

Each asset gets its own subfolder. The chosen folder is persisted to add-on
preferences.

### Dev notes

A session-scoped notes system for tracking per-asset development context while
authoring.

## Install

This is a Blender Extension. In Blender 5.0+:

1. Download the packaged `.zip` (or build it — see below).
2. Drag the `.zip` into Blender, or use *Edit → Preferences → Get Extensions →
   Install from Disk*.
3. Enable **No3d Asset Developer**.

Set your default export/WIP folder and extraction method in the add-on
preferences and the N-panel.

## Export output

Each exported asset produces:

```
target/
└── Asset_Name/
    ├── Asset_Name.blend     # individual .blend, metric units preserved
    ├── Asset_Name.json      # metadata (Shopify-compatible structure)
    ├── icon_Asset_Name.png  # thumbnail / preview image
    └── desc_Asset_Name.txt  # description text
```

The JSON is structured for storefront ingestion (title, handle, vendor,
product_type, tags, variants with generated SKU, and namespaced metafields such
as asset type, Blender version, and export date).

## Building the extension

With Blender on your `PATH`, from the repo root:

```bash
blender --command extension validate
blender --command extension build
```

`build` produces the upload-ready `no3d_asset_developer-3.0.0.zip`. The `[build]`
table in `blender_manifest.toml` controls exactly which files ship — dev-only
files (tests, demos, planning docs) are excluded.

## Development

- `__init__.py` — registration, preferences, WindowManager props
- `operators.py` — export operators and directory pickers
- `ui.py` — Asset Browser context menu + N-panel
- `extraction_methods.py` — Method A / Method B dispatch
- `blend_export.py` + `_export_single_asset.py` — Template Append subprocess
- `wip_sync.py` — mark/save/rename auto-sync handlers
- `utils.py` — metadata, thumbnails, JSON generation
- `notes/` — dev notes system

## License

Copyright (C) 2026 The Well Tarot, LLC. Released under the GNU General Public
License v3.0 or later. See [LICENSE](./LICENSE).
