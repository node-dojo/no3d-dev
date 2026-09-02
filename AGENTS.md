# AGENTS.md

Entry point for AI agents (Codex, Claude Code, or any future
agent) landing in this repo. Read this before touching code. If you see
"CLAUDE.md" referenced anywhere in tooling, treat this file as the source of
truth — it applies to all agents, not just Claude.

## What this is

**No3d Dev** — a monorepo hosting multiple independent Blender extensions,
served as a single self-hosted extension repository. Not itself a Blender
extension; each subdirectory under `extensions/` is one installable extension
with its own manifest, `AddonPreferences`, version, and release cadence.

- Extension repository URL: `https://node-dojo.github.io/no3d-dev/index.json`
- The GitHub repo is `github.com/node-dojo/no3d-dev` (renamed from
  `no3d-asset-developer` in v4.0.0)
- The local working directory may still be at
  `/Users/joebowers/Projects/no3d-asset-developer` — GitHub's redirect keeps
  the old remote URL working; the folder name is cosmetic

Extensions currently in the repo:

- `agent_bridge` — routes agents to the intended live Blender instance;
  vendored from `github.com/node-dojo/agent-bridge`
- `canvas_editor` — experimental Blender-native spatial document and media
  canvas with borderless GPU-skinned cards over real node mechanics
- `send_nodes` — Blender-native node-group exchange; vendored from
  `github.com/node-dojo/Send-Nodes`
- `no3d_asset_developer` — asset export pipeline and dogfood host for the
  separable Git Assets and Send Nodes modules
- `no3d_cad_wip` — experimental Blender-native direct-modeling and feature
  graph orchestration container; keep exploratory features here until their
  native-file portability and interaction model are proven
- `no3d_save_reload` — independent numbered-save and relaunch extension
- `no3d_camera_utilities` — vendored public camera/render utilities

**Claude Pair is retired.** Agent Bridge is its supported successor. Historical
Claude Pair plans remain only as records of the earlier implementation and must
not be treated as current architecture or an extension to restore.

## Non-negotiables (read before editing)

- **One `AddonPreferences` per sub-add-on.** Each extension in `extensions/`
  owns its own preferences class. No `HOST_PACKAGE` gymnastics — that rule
  died with the meta-add-on shape in v4.0.0. If you see a subpackage inside
  an extension needing prefs, that subpackage still reads
  `bpy.context.preferences.addons[__package__.rsplit(".", 1)[0]].preferences`
  (where the rsplit gets you back up to the extension package), but that's
  an internal-to-extension mechanism, not a cross-extension one.
- **No cross-extension Python imports.** An extension may call another via
  `bpy.ops.<other_extension>.<op>()` and must degrade gracefully if the
  target isn't installed/enabled. Never `from other_extension import …`.
- **After any registration-touching change, run `tools/check_register.sh`.**
  It iterates every extension and must print `REGISTER_OK` after listing each
  as `<ext_name>_OK`. This is the gate.
- **Version discipline, per extension.** Each extension's
  `blender_manifest.toml` `version` and `__init__.py` `bl_info["version"]`
  must agree, bumped together, always.
- **Don't rebuild what's already working:**
  - `extensions/no3d_asset_developer/repo_registration.py` — subscribes new
    installs to the No3d Dev extension repo. Already works.
  - `tools/publish_repo.sh` — builds all + generates index + force-pushes
    gh-pages. Already works.
  - The Supabase WIP-library publisher at `<The Well Code>/no3d-remote-publish/`
    is a *different* pipeline (ships asset `.blend` files, not add-on code) —
    do NOT conflate.
- **Platform: macOS only** for No3d Save & Reload. It fails gracefully via
  `self.report({"ERROR"}, …)` when its application/relaunch boundary is absent.

## Blender quirks / gotchas

- **Outer repo dir is hyphenated; extension dirs are underscore-safe.** The
  outer working directory (`no3d-asset-developer` on disk today,
  `no3d-dev` post-rename cosmetics) has a hyphen and isn't a valid Python
  module name — but that doesn't matter because we never add it to
  `sys.path`. Each `extensions/<name>/` is underscore-safe by convention
  (`no3d_asset_developer`, `agent_bridge`, etc.); the extension dir
  name IS the Python module name. `check_register.sh` adds
  `extensions/` (not the outer repo dir) to `sys.path` and imports the
  extension directly. No symlink shim needed at the extension level.
- **`AddonPreferences` subclasses are NOT exposed on `bpy.types`.** Reproduced
  outside this add-on with a throwaway class. `hasattr(bpy.types, '<NAME>')`
  is **always False and misleading** for AddonPreferences subclasses — use
  `<PrefsClass>.is_registered`. Operators and Panels DO appear on `bpy.types`
  after `register_class`; this quirk only bites for `AddonPreferences`.
- **Bare `mod.register()` doesn't populate `bpy.context.preferences.addons[key]`.**
  Blender's real addon-enable path is what registers the addon entry; a
  lightweight harness that only calls `register_class` on the prefs class
  won't. To check that a preference *property* is declared, read it from the
  class itself: `<PrefsClass>.bl_rna.properties['<name>']`, not through
  `bpy.context.preferences.addons[...]`.
- **Headless Blender + enabled user add-ons often hangs.** Learned the hard
  way. Any custom `--background --python …` run should start with
  `--factory-startup` (loads no user prefs, so no user-enabled add-ons come
  along) and register only what the harness needs. If you're launching
  Blender headlessly with the user's normal config, expect intermittent hangs
  where an add-on's `register()` opens a modal / touches the network / spawns
  a thread. Rule of thumb: **headless = --factory-startup + only-the-extension-under-test**.
  This is why `check_register.sh` uses `--factory-startup` and directly
  `mod.register()`s only the target extension.
- **Blender binary path is env-overridable.** Default is
  `/Applications/Blender 5.2 Beta.app/Contents/MacOS/Blender`. Every shell
  script honors `${BLENDER:-<default>}` so machines with a stable Blender
  install (e.g. the work Mac when 5.2 goes stable) don't break.

## Cross-extension conventions

- **Classname prefixes.** Multiple sub-add-ons can register panels into the
  same `NO3D Dev` N-panel tab (Blender merges by `bl_category`), but every
  registered class needs a globally unique classname across all installed
  extensions. Use per-extension prefixes:
  - `NO3D_AD_*` — no3d_asset_developer
  - `NO3D_SR_*` — no3d_save_reload
  - `NO3D_AB_*` — agent_bridge
  - `NO3D_CAD_*` — no3d_cad_wip
- **Cross-extension calls via `bpy.ops` only.** Fine to call
  `bpy.ops.no3d_asset_developer.export_single_asset()` from another
  sub-add-on, but wrap in try/except so the caller degrades if the target
  isn't installed/enabled. No `from other_extension import …`.
- **Shared code.** Duplicate small utilities per-extension (< 200 lines).
  Bigger shared machinery (like the template-append export pipeline in
  `extraction_methods.py` / `blend_export.py` / `_export_single_asset.py`)
  lives in *one* extension and is called via operators from elsewhere.

## Workflow: spec-driven development

Non-trivial features go through `.superpowers/sdd/`:

1. **Brief** in `.superpowers/sdd/task-N-brief.md` — required steps, files,
   interfaces, verification.
2. **Implement** on a feature branch, checkbox by checkbox.
3. **Report** to `.superpowers/sdd/task-N-report.md` — what shipped, what
   deviated, what was verified. Deviations get flagged in the report, not
   silently absorbed.
4. **Ledger** at `.superpowers/sdd/progress.md` — one line per task.

Design specs and implementation plans live in `docs/superpowers/{specs,plans}/`.
Never edit a spec while executing its plan — capture the divergence in the
task report and update the spec afterward.

## Cowork agent specifics

- The **Blender MCP** tools (`mcp__Blender__*`) are available in Cowork
  sessions. They're the best way to interactively verify class registration,
  inspect the running scene, or take viewport screenshots — use them
  *alongside* (not instead of) `tools/check_register.sh`, which remains the
  canonical automation-friendly gate.
- Cowork agents run in a sandbox, not the user's login shell — env vars,
  aliases, and `PATH` from the user's shell rc files are NOT inherited.
  Explicitly set `BLENDER=…` and full paths in every shell command.
- If a task needs a native macOS action outside Blender, prefer the
  filesystem connector; fall back to "Control Your Mac" / Desktop Commander
  per the user's stated preference.

## Vendoring: sub-extensions sourced from external repos

Some sub-extensions have an **external repo as their source of truth** — code
is authored there, the copy in `extensions/<name>/` is a mirror. Vendored
extensions are declared in `vendor.toml` at the repo root:

```toml
[no3d_camera_utilities]
source = "https://github.com/node-dojo/no3d-camera-utilities.git"
ref = "main"
subdir = "no3d_camera_utilities"
```

**Rules:**

- **Do NOT edit the code of a vendored extension in this repo.** Edits happen
  in the source repo; `tools/vendor_sync.sh <name>` pulls them here.
- **Local-only files (like `blender_manifest.toml`) are preserved by sync.**
  Vendor sync uses rsync without `--delete`, so a locally-authored manifest
  survives even if the upstream doesn't ship one.
- **Version discipline** for a vendored extension: the local
  `blender_manifest.toml` version is authoritative for what's served by the
  extension repo. `bl_info` in the upstream `__init__.py` is informational;
  drift between them is OK but should be resolved when the upstream cuts a
  release.
- **`.vendor_last_sync`** sentinel file records the last-synced upstream
  commit; committed to git for reviewability.

Currently vendored: `agent_bridge` ← `github.com/node-dojo/agent-bridge`, and
`no3d_camera_utilities` ← `github.com/node-dojo/no3d-camera-utilities`.

## Ship pipeline

`tools/ship.sh <extension_id> <version> [--notes "..."] [--sync-vendor] [--dry-run]`
is the deterministic ship spine. Runs preflight (clean tree, on main,
harness passes), optionally syncs upstream for vendored extensions, bumps
manifest + bl_info, builds every extension, **prunes old-version zips from
`dist/` and the scratch repo dir (keeps only the current version per
extension)**, force-pushes gh-pages, commits + tags + pushes main, appends
to `$VAULT_001/PROJECTS/no3d tools/ship-log.md` if the env var is set.

**Typical shipping flow:**

- Authored-in-place extension: `tools/ship.sh no3d_asset_developer 4.0.2 --notes "..."`
- Vendored extension: bump version in the upstream repo → commit + push
  upstream → in No3d Dev, `tools/ship.sh no3d_camera_utilities 1.0.1 --sync-vendor --notes "..."`

Design context: `docs/superpowers/specs/2026-07-08-ship-pipeline-design.md`
(pre-monorepo shape; ship.sh as built already reflects the monorepo shape).
Gumroad publishing is intentionally parked; add later with a `--gumroad` flag.

Session logs live in the vault, not the repo:
`$VAULT_001/PROJECTS/no3d tools/ship-log.md`. Absolute dates only.

## Directory map

```
no3d-dev/                                # repo root (folder still named
│                                        # no3d-asset-developer locally)
├── extensions/
│   ├── agent_bridge/                    # vendored from canonical repo
│   ├── send_nodes/                      # vendored from canonical repo
│   ├── no3d_save_reload/                # authored here
│   ├── no3d_camera_utilities/           # vendored from canonical repo
│   ├── no3d_cad_wip/                    # experimental authored extension
│   └── no3d_asset_developer/            # asset workflow + dogfood host
│       ├── blender_manifest.toml
│       ├── __init__.py                  # bl_info, NO3D_AddonPreferences
│       ├── operators.py, ui.py, utils.py
│       ├── wip/, notes/                 # internal subpackages
│       ├── extraction_methods.py + blend_export.py + _export_single_asset.py
│       │                                # retained internal template-append
│       │                                # pipeline; re-enable via
│       │                                # wm.no3d_extraction_method
│       └── repo_registration.py         # subscribes new installs to No3d Dev
├── tools/
│   ├── check_register.sh                # iterates extensions/*/; the gate
│   ├── build_all.sh                     # headless extension build per ext
│   ├── publish_repo.sh                  # aggregates zips + gh-pages push
│   ├── vendor_sync.sh                   # pulls upstream source for vendored exts
│   └── ship.sh                          # bump → build → prune → publish → tag → log
├── vendor.toml                          # declares vendored sub-extensions
├── docs/superpowers/{specs,plans}/      # design specs + implementation plans
├── .superpowers/sdd/                    # active task briefs, reports, ledger
├── AGENTS.md                            # this file
├── README.md                            # user-facing
├── HANDOFF.md                           # historical snapshot (pre-restructure)
├── LICENSE
└── dist/                                # gitignored, populated by build_all
```

## Current state / getting oriented

```bash
git status && git branch --show-current
git log --oneline -10
cat .superpowers/sdd/progress.md         # what the current SDD run is on
tools/check_register.sh                  # should print REGISTER_OK
```

## Lessons / gotchas (append here after corrections)

- Never create or save the user's Blender preferences from a stripped,
  temporary, or test-only extension repository state. Registration tests must
  use `--factory-startup` and must not call `bpy.ops.wm.save_userpref()`. A live
  development cutover must preserve the existing repository collection,
  enabled third-party add-ons, keymaps, themes, and add-on preferences; change
  only the explicitly retired/replaced module entries.

<!--
When you get corrected on something — by the user or by a broken assumption
in a plan/spec — write the durable lesson as a bullet here so the next agent
starts with your correction as its baseline. Keep bullets tight. Once a
lesson stabilizes, promote it into the section above (Blender quirks or
Non-negotiables) and remove it from this list.
-->

- Do not write `hasattr(bpy.types, '<PrefsClass>')` — always False for
  `AddonPreferences` subclasses. Use `is_registered` (see Gotchas).
- Do not check prefs *props* via `bpy.context.preferences.addons[key]` in a
  bare-harness context — read them from `<PrefsClass>.bl_rna.properties`.
- Headless Blender with the user's normal add-ons enabled often hangs —
  always `--factory-startup` in scripts, and register only what the harness
  needs.
- The outer working-tree folder can stay named anything (it's not on
  `sys.path`); what matters is that every `extensions/<name>/` dir name is
  underscore-safe because THAT is the Python module name.
- `LICENSE` and `README.md` at the outer root don't get bundled into any
  extension zip — the manifest's `[build].paths` are relative to
  `--source-dir` which is the extension's own dir. Add a build-time copy
  step in `build_all.sh` if a future release needs them inside the zip.
- Parse Blender extension modules as
  `bl_ext.<repository>.<extension_id>[.<submodule>]`. The owner is segment 3,
  not the repository segment (`user_default`, `NO3DTools`, and so on). Getting
  this wrong causes owner-based N-panel sorting to classify our panels as
  unrelated third-party add-ons.
- N-panel tabs merge and sort by exact registered `bl_category` strings.
  `NO3D Dev` and `No3D Dev` are different tabs, and changing source does not
  mutate classes already registered in a long-running Blender process. Verify
  live classes, normalize stale classes by unregistering/re-registering them,
  then rerun `npanel_order.apply_npanel_order()`.
- Blender exposes no declarative N-panel tab-order property. The practical
  programmatic mechanism is registration order: unregister category-bearing
  sidebar panels child-first, then register roots in desired category order
  and children afterward. Always restore foreign panels after partial errors.
- An add-on module's cached `_addon_keymaps` list is not proof that its items
  still exist in Blender. For live recovery, inspect the actual
  `window_manager.keyconfigs.addon` keymap and rebuild missing bindings with
  the module's unregister/register hooks. Keep plain F scoped to Object Mode
  so Mesh Edit Mode retains F = Make Face.
- A stale live extension can be repaired surgically without restarting or
  saving preferences: normalize only the affected registered panels, remove
  explicitly retired panels, rebuild missing add-on keymaps, and reapply tab
  ordering. Read back the exact live categories and bindings afterward; source
  inspection and `REGISTER_OK` alone do not prove the open process changed.
- N-panel navigation is one internal `power_panel/` feature suite. Its
  reconciliation order is restore hidden/numbered/routed state, discover live
  panels, route canonical categories, apply numeric display slots, then order
  categories. F5 owns live filter input; Option+Tab owns the spatial pie and
  invoked number selection. Never add global modifier-number bindings for
  Power Panel or split these concerns back into host-level sibling modules.
