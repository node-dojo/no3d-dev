# No3d Dev — Monorepo of Independent Extensions

> **Current amendment (2026-08-28):** The monorepo direction is implemented,
> but the package lineup changed. Agent Bridge is the supported successor to
> retired Claude Pair; there is no `no3d_claude_pair` extraction target. Agent
> Bridge, Send Nodes, and Camera Utilities are vendored from their canonical
> standalone repositories. Save & Reload is independently authored here.
> Later Claude Pair steps below are historical and must not be executed.

**Date:** 2026-07-08
**Target repo:** currently `github.com/node-dojo/no3d-asset-developer` → renaming to
`github.com/node-dojo/no3d-dev`
**Supersedes:** the "meta-add-on with subpackages" architecture that landed as
v3.2.0 (Save & Reload + Claude Pair folded into `no3d_asset_developer`). That
merge is not being reverted — it was correct given what we knew at the time,
and it taught us the exact shape of the pain that this restructure removes.

## Terminology

- **No3d Dev** — the human-facing name of this collection / monorepo / extension
  repository. **Not itself a Blender extension.** It's the umbrella that hosts
  many extensions, served at one URL. Rename applies to the GitHub repo, the
  gh-pages URL, and the `--html` landing page produced by
  `extension server-generate`.
- **Sub-add-on / sub-extension** — one of the independent, standalone Blender
  extensions inside `extensions/`. Each has its own manifest, its own
  `AddonPreferences`, its own version, its own release cadence.
- **Extension repository URL** — `node-dojo.github.io/no3d-dev/index.json`
  (new). Was `.../no3d-asset-developer/index.json` (old — deprecated after
  migration).
- The extension id **`no3d_asset_developer`** stays exactly as-is. It's now one
  sub-add-on inside No3d Dev rather than the "host."

## Goal

Move to Blender's intended shape for a stable of related tools: one dynamic
extension repository serving many independent extensions, each installed and
updated on its own cadence, all subscribed to by one URL on the user's machine.

## Why

Everything the current single-`AddonPreferences` rule forced us to work around
disappears:

- No more `HOST_PACKAGE = __package__.rsplit(".", 1)[0]` inside every subpackage
- No more folding N features' preference properties into one giant
  `NO3D_AddonPreferences.draw()`
- No more "bump the meta version to 3.3.0 to ship a Claude Pair tweak that Save
  & Reload didn't care about"
- Users install à la carte via Blender's native Get Extensions UI
- Each sub-add-on can be spun off as its own product later (Superhive, Gumroad,
  wherever) without unmerging first

The distribution pipeline changes are small — Blender's `extension server-generate`
already handles a directory containing many zips. The reshaping is 90%
directory layout and 10% tooling.

## Non-negotiables

- **Blender extension conventions** stay identical to what AGENTS.md already
  captures. The quirks list (AddonPreferences not on `bpy.types`, bare
  `mod.register()` doesn't populate `bpy.context.preferences.addons[key]`,
  headless-with-addons hangs, `${BLENDER:-…}`) applies **per sub-add-on** —
  each has its own `check_register.sh`-equivalent gate.
- **One `AddonPreferences` per sub-add-on.** The former "single-owner in the
  whole add-on" rule becomes "single-owner per sub-add-on." Each sub-add-on
  owns its own class.
- **Extension IDs are stable.** `no3d_asset_developer` is `no3d_asset_developer`
  forever. Users who installed v3.2.0 keep their prefs when we ship
  `no3d_asset_developer` v4.0.0 as a standalone (unmerged) extension.
- **Version discipline per sub-add-on.** Each sub-add-on's
  `blender_manifest.toml` version must match its `__init__.py` `bl_info["version"]`.
  Same rule, applied N times.
- **No cross-extension Python imports.** Sub-add-ons may call each other via
  `bpy.ops.<name>(...)` (Blender-level, degrades gracefully if the other
  extension isn't installed/enabled), but must NEVER `from other_extension
  import …`. Extensions can't depend on each other at the Python level under
  the extension system.
- **Unique panel/operator classnames per sub-add-on.** Multiple sub-add-ons
  can register into the same `NO3D Dev` N-panel tab, but every registered
  class needs a globally unique name. Use per-add-on prefixes: `NO3D_AD_*`,
  `NO3D_SR_*`, `NO3D_CP_*`, `NO3D_AB_*`.
- **Small shared utilities → duplicate per sub-add-on.** Bigger shared
  machinery (e.g. the retained template-append export pipeline) lives in
  one sub-add-on and is exposed via operators for others to call.

## Naming decisions (confirmed with Joe 2026-07-08)

- Umbrella / repo → **No3d Dev**
- GitHub repo rename: `no3d-asset-developer` → `no3d-dev`
- gh-pages URL: `node-dojo.github.io/no3d-dev/index.json`
- `no3d_asset_developer` stays as a sub-add-on (keeps its id, keeps its user
  install continuity)
- Additional sub-add-ons planned:
  - `no3d_agent_bridge` (new, being developed alongside)
  - `no3d_save_reload` (unmerge target, Step 4)
  - `no3d_claude_pair` (unmerge target, Step 5)
  - future tools slot in the same way

## New repo structure

```
no3d-dev/                             # renamed from no3d-asset-developer
├── extensions/
│   ├── no3d_asset_developer/         # current v3.2.0 content moves here
│   │   ├── blender_manifest.toml
│   │   ├── __init__.py
│   │   ├── operators.py
│   │   ├── ui.py
│   │   ├── ...
│   │   ├── wip/                      # still a subpackage OF THIS extension
│   │   ├── notes/
│   │   ├── save_reload/              # still merged here at Step 1 landing
│   │   └── claude_pair/              # still merged here at Step 1 landing
│   ├── no3d_agent_bridge/            # Step 2
│   ├── no3d_save_reload/             # Step 4 (unmerge target)
│   └── no3d_claude_pair/             # Step 5 (unmerge target)
├── shared/                           # optional; only if a util grows past ~200
│                                     # lines and duplication becomes silly
├── tools/
│   ├── build_all.sh                  # NEW — iterates extensions/*/, builds each
│   ├── publish_repo.sh               # UPDATED — uses build_all output
│   ├── check_register.sh             # UPDATED — iterates extensions/*/
│   └── ship.sh                       # NEW (later) — per-extension ship
├── docs/superpowers/{specs,plans}/
├── .superpowers/sdd/
├── AGENTS.md                         # rewritten for the monorepo shape
└── README.md                         # rewritten for the monorepo shape
```

Note: at Step 1 landing, `no3d_asset_developer/` still contains the merged
`save_reload/` and `claude_pair/` subpackages. Those move to their own
top-level extensions at Steps 4 and 5. Doing it in that order means Step 1
is a pure move — no code inside `no3d_asset_developer` needs to change.

## URL migration (the one-time client pain)

The existing gh-pages URL (`node-dojo.github.io/no3d-asset-developer/index.json`)
is baked into `repo_registration.py`, which is what auto-subscribes both Macs.
The new URL will be `node-dojo.github.io/no3d-dev/index.json`.

Two ways to handle it. Pick before shipping Step 1:

**Option A — Ship a bridge release (recommended).** Cut one last v3.2.x
release from the OLD URL that:
- Updates `repo_registration.py` to add the NEW URL as an additional
  subscription (keeps the old one for backup)
- After both Macs auto-pull that release, they're subscribed to both URLs
- Ship v4.0.0 (the restructured `no3d_asset_developer` as a standalone
  sub-add-on) from the NEW URL only
- The OLD URL falls silent naturally

Zero manual intervention on either Mac. Downside: one extra release.

**Option B — Manual resubscribe.** After Step 1 lands, edit the extension
repo URL in Preferences → Get Extensions on both Macs, one time. Two clicks
each. Less clever, dead-simple.

Recommendation: **Option B.** Two machines, one manual step each. The bridge
release adds complexity you'll be maintaining alone for one migration.

## Tooling updates (concrete but small)

### `tools/build_all.sh` (new)

```bash
#!/bin/bash
set -euo pipefail
BLENDER="${BLENDER:-/Applications/Blender 5.2 Beta.app/Contents/MacOS/Blender}"
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$PROJECT/dist"

mkdir -p "$DIST"
for ext_dir in "$PROJECT"/extensions/*/; do
  ext_name="$(basename "$ext_dir")"
  version=$(grep '^version' "$ext_dir/blender_manifest.toml" | head -1 | cut -d'"' -f2)
  zip_name="${ext_name}-${version}.zip"
  echo "==> Building $zip_name"
  "$BLENDER" --factory-startup --command extension build \
    --source-dir "$ext_dir" --output-filepath "$DIST/$zip_name"
done
```

### `tools/publish_repo.sh` (updated)

Iterate `dist/*.zip` (produced by `build_all.sh`) into the scratch repo dir,
run `extension server-generate --repo-dir … --html` (already handles many
zips), force-push to gh-pages. The push URL becomes `no3d-dev.git` after the
rename.

### `tools/check_register.sh` (updated)

Loops over `extensions/*/`. For each: symlink-import the extension with its
underscore-safe name (each already has an underscore-safe id: `no3d_asset_developer`
etc. — no hyphen problem at the extension level), call `mod.register()`,
assert `<PrefsClass>.is_registered`, call `mod.unregister()`, verify
teardown. Passes only if all extensions pass. Same `--factory-startup` +
"register only what we're testing" discipline.

### `tools/ship.sh` (new, later)

`ship.sh <extension_id> <version> [--notes …]`. Preflight checks the
target extension's manifest ↔ bl_info agreement (not the others'). Bumps the
target's two version fields. Runs `build_all.sh` (which builds everything —
cheap, and keeps the aggregated index consistent). Runs `publish_repo.sh`.
Commits + tags + pushes. Appends to vault ship log. Everything from the
existing ship-pipeline spec applies; only "which extension am I versioning"
changes.

## Cross-extension conventions

**UI panels.** Multiple sub-add-ons registering into the same `NO3D Dev`
N-panel tab is a design goal. Blender merges panels by `bl_category`
seamlessly. Each add-on's panel classes need unique names — prefix
convention:

- `NO3D_AD_*` — no3d_asset_developer
- `NO3D_SR_*` — no3d_save_reload
- `NO3D_CP_*` — no3d_claude_pair
- `NO3D_AB_*` — no3d_agent_bridge

Operators follow the same prefix pattern; keep the `bl_idname` verb form
that already works (`save_and_reload.run`, `claude_pair.pair_now`, etc.).

**Cross-extension operator calls.** Fine to do
`bpy.ops.no3d_asset_developer.export_single_asset()` from another sub-add-on
IF the target is installed and enabled. Wrap in a try/except that reports
gracefully:

```python
try:
    bpy.ops.no3d_asset_developer.export_single_asset()
except (AttributeError, RuntimeError):
    self.report({"ERROR"}, "This action requires No3d Asset Developer to be enabled")
    return {"CANCELLED"}
```

**Shared code.** Duplicate small utilities (< 200 lines total). Bigger
machinery — the template-append export pipeline in
`extraction_methods.py` / `blend_export.py` / `_export_single_asset.py` —
stays owned by `no3d_asset_developer` and is called via operators from
elsewhere. Don't put an `import` from a sibling extension anywhere.

## Phased plan (this spec's roadmap)

Each phase is a separate implementation plan file. This spec is the
overarching architecture; the plan docs are the checkbox execution scripts.

- **Step 1 — Restructure the shell.** Rename repo, move current v3.2.0
  content into `extensions/no3d_asset_developer/`, update `check_register.sh`
  and `publish_repo.sh` to iterate. Migrate URL (Option B). Verify both
  Macs pull the new URL successfully.
  → `docs/superpowers/plans/2026-07-08-restructure-to-monorepo.md`

- **Step 2 — Add `no3d_agent_bridge` as an independent extension.** Prove the
  multi-extension publish + install + update flow on a greenfield sub-add-on
  with no unmerge risk.
  → future plan doc

- **Step 3 — Build `tools/ship.sh` against the multi-extension shape.**
  Preflight, version bump for one target extension, build all, publish,
  commit, tag, push, log. `--no-gumroad` is the default; Gumroad flag is
  additive per the existing ship-pipeline spec.
  → future plan doc

- **Step 4 — Unmerge `no3d_save_reload` → its own extension at v1.0.0.**
  Pull its 3 preference properties back out of `NO3D_AddonPreferences` into
  a fresh `NO3D_SR_AddonPreferences`. Rename its classes to the `NO3D_SR_*`
  prefix. Bump `no3d_asset_developer` to remove Save & Reload.
  → future plan doc

- **Step 5 — Unmerge `no3d_claude_pair` → its own extension at v1.0.0.**
  Same shape as Step 4 for the 12 Claude Pair prefs and its panel/operators.
  → future plan doc

Steps 4–5 are boring reversal work; the current merge plan is your
reference for exactly which props belong to which. Not urgent; do them
after Step 2 proves the multi-extension pipeline.

## Verification approach (unchanged in spirit)

- `tools/check_register.sh` remains the gate. It grows to iterate over every
  sub-add-on, and it fails if any one of them fails. The `--factory-startup`
  discipline is unchanged.
- Each sub-add-on's own `NO3D_*_AddonPreferences.is_registered` is asserted
  after `mod.register()`, teardown re-asserted after `unregister()`.
- Prefs *props* are still checked via `<PrefsClass>.bl_rna.properties[...]`,
  not through `bpy.context.preferences.addons[...]`.

## Out of scope

- Blender-Foundation-visible listing on extensions.blender.org (that platform
  is GPL-only + no-payment, and our repo hosts free tools mixed with
  potentially-paid ones later — self-hosted stays right).
- Gumroad publishing pipeline — parked. `ship.sh` will land with
  `--no-gumroad` as the default; add the leg later if we ever want to sell
  something from Gumroad again.
- Superhive publishing — parked. Same reason. If we ever list a sub-add-on
  there, it's a per-extension decision, not an umbrella-level one.
- Cross-extension shared-wheel bundling — overkill for the current scale.
  Reconsider when duplication actually hurts.

## AGENTS.md follow-up (required in Step 1)

The current AGENTS.md was written for the single-AddonPreferences meta-add-on
shape. Step 1's plan includes rewriting these sections:

- "Non-negotiables" — "one AddonPreferences" becomes "one per sub-add-on".
  Drop the `HOST_PACKAGE = __package__.rsplit(".", 1)[0]` rule.
- "Directory map" — reflects `extensions/*/`.
- "Cowork agent specifics" — unchanged.
- "Blender quirks / gotchas" — mostly unchanged, but the "hyphenated repo
  dir isn't importable" note only applies to the outer repo, not the
  extension dirs (which are already underscore-safe).
- Add a "Cross-extension conventions" section mirroring the one in this
  spec.
