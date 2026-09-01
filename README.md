# No3d Dev

A monorepo of Blender extensions authored by NO3D Tools, distributed as a
single self-hosted extension repository. One subscription URL in Blender's
Get Extensions gives you every extension below — installable and updatable
independently.

- **Repository URL:** `https://node-dojo.github.io/no3d-dev/index.json`
- **Blender:** 5.0+
- **License:** GPL-3.0-or-later
- **Umbrella name in Blender:** *No3d Dev*

## Subscribe (recommended)

In Blender 5.0+:

1. Open **Edit → Preferences → Get Extensions → Repositories → +** (new remote).
2. Paste `https://node-dojo.github.io/no3d-dev/index.json`.
3. Refresh. Every extension in this repo appears in **Get Extensions**.
4. Install the ones you want; each has its own preferences page and updates
   on its own cadence.

## Extensions in this repo

### No3d Asset Developer

Turns marked assets into clean, individually-packaged `.blend` files with
metadata, thumbnails, and dev notes — for maintaining a distributable asset
library. Git Assets and Send Nodes are developed here as separable dogfood
modules before their tentative independent public distribution.

Location once installed: **Asset Browser → Context Menu** and
**3D Viewport → N-Panel → No3D Dev**.

#### Transparent Media

Open **3D Viewport → N-Panel → No3D Dev → Transparent Media**. The two scene
buttons render a transparent PNG master sequence with the current camera,
engine, resolution, frame range, and FPS, then create either:

- a transparent ProRes 4444 `.mov`; or
- a looping transparent `.gif`.

The same panel converts an existing numbered PNG sequence. Leaving its Folder
field empty uses the scene's current Output folder. Output names and locations
are inferred, and the rendered PNG sequence remains available as the reusable
master. GIF has one-bit transparency; use the MOV when soft alpha edges matter.

Conversion requires the `ffmpeg` executable. Common Homebrew and shell paths
are detected automatically; an override is available in the extension's
preferences.

#### Image planes

Both **Add → Image → Mesh Plane** and `Shift+5` open Blender's native image
plane importer with the NO3D clipboard-plane material template preloaded:
Shadeless, alpha enabled, Blended transparency, Closest interpolation, and
Repeat extension. The native file browser and placement workflow remain
unchanged. `Cmd+Shift+V` continues to paste the clipboard directly as a plane
using the same template.

Source: `extensions/no3d_asset_developer/`.

#### Power Panel

Power Panel organizes and navigates the 3D View sidebar without depending on
CleanPanels. It routes local tools into intent-based categories, keeps native
Blender tabs first, adds stable numbered bookmarks, and provides two fast
navigation paths:

- `F5` enters live tab-filter input in the Tool Settings field.
- `Option+Tab` opens the spatial Power Panel pie; choose by gesture/click or
  press a displayed number while it is open.

Slot destinations are editable in No3d Asset Developer preferences. Defaults
work immediately, and Power Panel does not reserve global modifier-number
shortcuts. Its implementation is the internal `power_panel/` subpackage.

### Agent Bridge

Registers each live Blender by `.blend` filename and lets agents select the
correct instance without manually managing ports. Its canonical source remains
`github.com/node-dojo/agent-bridge`; the Blender extension is vendored here for
one managed development/install surface. Agent Bridge supersedes and retires
the former Claude Pair workflow.

Source projection: `extensions/agent_bridge/`.

### Send Nodes

Shares Blender-native node-group bundles by URL. Its canonical public source
remains `github.com/node-dojo/Send-Nodes`; the extension is vendored here and
dogfooded alongside Asset Developer.

Source projection: `extensions/send_nodes/`.

### No3d Save & Reload

Saves the current file as its next numbered iteration, quits Blender, and
reopens that iteration in the same Blender application.

Source: `extensions/no3d_save_reload/`.

## Development

Each extension is a self-contained subdirectory under `extensions/`. Repo-wide
tooling lives at the outer root:

- `tools/check_register.sh` — headless register/unregister gate; iterates
  every extension. Must print `REGISTER_OK` after any registration-touching
  change.
- `tools/build_all.sh` — headless `extension build` per extension into `dist/`.
- `tools/publish_repo.sh` — builds all extensions, aggregates zips, generates
  the static repo `index.json`, force-pushes to gh-pages.

For contributor / AI-agent onboarding, read `AGENTS.md` at the repo root
before touching code. It carries the non-negotiables, Blender quirks, and
the cross-extension conventions (classname prefixes, `bpy.ops`-only for
cross-extension calls, no Python imports across extensions).

## License

Copyright (C) 2026 The Well Tarot, LLC. Every extension in this repo is
released under the GNU General Public License v3.0 or later. See
[LICENSE](./LICENSE).
