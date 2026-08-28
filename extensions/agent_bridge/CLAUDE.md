# Agent Bridge — middle-tier instructions

This is the **Agent Bridge** layer of a three-tier instruction hierarchy
(**Global → Agent Bridge → Project**). Rules here apply to any Blender
session where the Agent Bridge add-on is serving. They take precedence over
Global rules but yield to Project rules when they conflict.

Everything in this file is either:

- **[POLICY]** — a rule, deliberate, not derivable from filesystem state. Trust unless changed here.
- **[LIVE: `<cmd>`]** — a claim that must be verified at session start; run the command, use its output.
- **[HISTORICAL]** — for context; may be stale. Do not rely on for action.

If you find yourself hardcoding a path from this file into new code, **stop**
and use the discovery process instead. This doc is a set of rules for
finding the world, not a snapshot of it.

Assumes: Blender 5.x extensions (manifest-based), macOS filesystem,
`$SHELL`-provided PATH. On a different Blender major or OS, treat structural
claims as suggestions and verify.

---

## Domain expertise to bring by default  [POLICY]

Every session under Agent Bridge should assume work at the intersection of:

- **CGI** — Blender-first, real-time and offline rendering, Eevee & Cycles,
  glTF/USD pipelines, Verge3D interop.
- **Applied Geometry** — geometry nodes, curve/surface math, parametric
  modeling, tolerance/fit reasoning for physical parts.
- **Design** — visual composition, typography, brand systems, layout;
  outputs should read as intentional, not defaults.
- **Class-A surface CAD** — G2/G3 curvature continuity, highlight/reflection
  quality, engineering-grade surface topology (industrial-design-native
  vocabulary is welcome).
- **Computational Design Theory** — rule-based / parametric / generative
  systems; treat "make it look right" as an optimization problem with
  constraints when appropriate.

Default to precise vocabulary from these fields rather than beginner
paraphrasing. If a term isn't in the user's context, name it and briefly
gloss it once.

---

## Anchor paths — the only stable references  [POLICY]

Every path claim resolves through these env vars. A folder rename or
machine migration is a one-var edit; do not hardcode absolute paths
downstream of this doc.

| Env var                     | Default                                                                                             | What lives there                            |
|-----------------------------|-----------------------------------------------------------------------------------------------------|---------------------------------------------|
| `$NO3D_PROJECTS_ROOT`       | `$HOME/Projects`                                                                                    | Add-on and code repos                       |
| `$NO3D_MONOREPO`            | `$HOME/Projects/no3d-asset-developer`                                                               | No3d Dev monorepo (vendor.toml lives here)  |
| `$NO3D_BLEND_PROJECTS_ROOT` | `$HOME/Library/CloudStorage/Dropbox/Caveman Creative/THE WELL_Digital Assets/THE WELL_play files`   | Blender `.blend` project files              |
| `$VAULT_001`                | `$HOME/Vault_001`                                                                                   | Notes vault; ship log lives here            |
| `$AGENT_BRIDGE_SRC`         | `$HOME/Projects/agent-bridge/agent_bridge`                                                          | This add-on's canonical source              |

The Agent Bridge add-on's `resolve_anchors()` in `__init__.py` is the
runtime source of truth for these — call it from Python if you need the
resolved values programmatically.

---

## Session-start ritual  [POLICY]

Before making any non-trivial change, run this ritual (or trigger it from
the N-panel's **Refresh Drift Map** button, which does the equivalent):

1. **Anchors present?** — expand each env var above; confirm the path
   exists. Missing = flag before proceeding.
2. **Enumerate current add-on repos**:
   ```
   find "$NO3D_PROJECTS_ROOT" -maxdepth 4 -name blender_manifest.toml \
     -not -path '*/_archive/*' -not -path '*/.*'
   ```
   For each result's directory, gather:
   ```
   git -C <repo_root> remote -v
   git -C <repo_root> symbolic-ref --short HEAD
   git -C <repo_root> log --oneline -3
   git -C <repo_root> status --short
   ```
3. **Read vendor relationships** — parse
   `$NO3D_MONOREPO/vendor.toml`. Any extension listed there is
   **vendored**: its canonical source is the `source` URL at the pinned
   `ref`. The copy inside `$NO3D_MONOREPO/extensions/<id>/` is downstream —
   never edit it in place; `vendor_sync.sh` will clobber the changes.
4. **List recent `.blend` projects**:
   ```
   find "$NO3D_BLEND_PROJECTS_ROOT" -maxdepth 3 -name '*.blend' \
     -print0 | xargs -0 stat -f '%m %N' | sort -rn | head -20
   ```
   Useful when the current session's blend is unfamiliar and you need to
   know what neighbors exist.
5. **List asset libraries** configured in the running Blender:
   ```python
   import bpy
   for lib in bpy.context.preferences.filepaths.asset_libraries:
       print(lib.name, lib.path)
   ```
   Or, from a Python API session: use the `_asset_libraries()` helper in
   `agent_bridge/__init__.py`.

The **Refresh Drift Map** operator (`bpy.ops.agent_bridge.refresh_drift_map()`)
runs all of this and writes a timestamped markdown report to a Blender Text
datablock named `agent-bridge:drift-map` (and copies it to the clipboard).
Prefer that button over doing it by hand — the report is what should end up
in your context anyway.

---

## Rules for interpreting the drift map  [POLICY]

Classify every add-on repo you discover using these rules, in order:

1. **Vendored** — its `id` (from `blender_manifest.toml`) appears in
   `$NO3D_MONOREPO/vendor.toml`. Canonical source is the URL at `ref`; the
   local copy is a mirror. **Never edit the mirror.** Bump versions in the
   canonical repo, commit, push, then `tools/vendor_sync.sh <id>` from the
   monorepo.
2. **Authored-in-place inside the monorepo** — under
   `$NO3D_MONOREPO/extensions/` but NOT in `vendor.toml`. Edit here directly.
3. **Monorepo root itself** — has both `vendor.toml` AND `extensions/`.
   Read its `AGENTS.md` first (it is the authoritative doc for anything in
   that repo — do not restate its rules in this file).
4. **Standalone canonical repo** — outside the monorepo, with a git remote
   AND appears as a `source` in vendor.toml. This is where you edit
   canonically. After bumping, run `vendor_sync` inside the monorepo.
5. **Standalone product / publication target** — outside the monorepo, may
   or may not have a git remote, not referenced by vendor.toml. The
   user-facing published add-on. Features migrate here from No3d Dev when
   production-ready; new features should not be authored here directly.
6. **Archived** — anything under any `_archive/` directory. Do not use as a
   reference for new work. If an idea in one is relevant, resurrect it as a
   branch inside the monorepo, not as a floating folder.
7. **Non-git scratch** — a manifest-bearing directory with no git repo
   above it. Treat with suspicion; ask before writing to it.

**Drift red flags** to surface to the user:

- Any repo with `git status --short` output (uncommitted changes) when
  they said they were "done."
- Any vendored extension whose local copy differs from what
  `vendor_sync.sh --dry-run` would install (upstream advanced).
- Version-string mismatch between two copies of the same add-on
  (canonical vs. vendored vs. installed).
- The Agent Bridge install path vs. the source repo diverging.

---

## This add-on itself  [POLICY]

- **Canonical source**: `$AGENT_BRIDGE_SRC`
- **Installed copy** (Blender loads this): `$HOME/Library/verge3d_blender/addons/agent_bridge/`

Sync policy: currently separate copies. Preferred fix — symlink installed →
canonical:

```
ln -s "$AGENT_BRIDGE_SRC" \
   "$HOME/Library/verge3d_blender/addons/agent_bridge"
```

Until that's in place, mirror any edit made at the install path back to the
source repo (and commit) before ending a session.

**Registry** (`registry.py`): JSON files at `~/.blender-pairs/<pid>.json`,
one per serving Blender. Schema per `build_register_payload`:

```json
{
  "blender_pid": 12345,
  "port": 9877,
  "host": "localhost",
  "blendfile": "/absolute/path/to/scene.blend",
  "blendfile_stem": "scene",
  "started_at": 1721340000.0
}
```

- **Auto-serve (v0.2.0+):** on add-on register (Blender launch, addon enable),
  a deferred `bpy.app.timers` callback runs the serve operator so the
  instance is reachable without a click. A persistent `load_post` /
  `save_post` handler re-serves on file open / Save-As so the registry stem
  tracks the current .blend. Headless Blender (`bpy.app.background`) is
  skipped so tests aren't affected.
- Serve (manual): N-panel *Serve to Agents* → starts official Blender MCP
  on a free port in `9876–9999` → writes the registry entry. Also re-arms
  auto-serve if the user had stopped it this session.
- Stop: *Stop Serving* → stops MCP → removes the registry file → sets a
  session-scoped `_user_stopped` flag so `load_post`/`save_post` won't
  quietly restart the server. Cleared by clicking *Serve to Agents* again
  or restarting Blender.
- Unregister: stops the MCP server, removes the registry entry, tears down
  the handlers/timer.
- GC: `registry.live_instances()` prunes dead-pid entries on read.
- Target: the standalone `agent-bridge` MCP process (outside Blender)
  routes agent bpy calls to the matching entry by `.blend` stem.

**Key files** (both source and installed copy have the same layout):

- `__init__.py` — Blender-side operators + N-panel; anchor / discovery
  helpers live here (`resolve_anchors`, `discover_addon_repos`,
  `discover_blend_projects`, `discover_instruction_files`).
- `registry.py` — bpy-free registry read/write/GC. Runs both in Blender and
  in the standalone MCP subprocess.
- `serve_helpers.py` — port allocation + official MCP add-on start/stop.
- `bridge_server.py`, `bridge_tools.py`, `resolver.py` — standalone MCP
  server side (bpy-free; unused inside Blender).

**Hot-reload** after editing (from the Python console or MCP):

```python
import bpy, sys
addon_id = "bl_ext.addons.agent_bridge"
bpy.ops.preferences.addon_disable(module=addon_id)
for name in list(sys.modules):
    if name == addon_id or name.startswith(addon_id + "."):
        del sys.modules[name]
bpy.ops.preferences.addon_enable(module=addon_id)
```

**Manifest changes** (`blender_manifest.toml`) require a full extension
re-install — hot-reload will not pick them up.

---

## Ship pipeline  [LIVE: `$NO3D_MONOREPO/tools/ship.sh --help`]

`tools/ship.sh` inside `$NO3D_MONOREPO` is the deterministic ship pipeline
(bump → build → prune old zips → publish → git tag → vault ship-log append).
For vendored extensions, `--sync-vendor` pulls upstream first. See the
script's own top-of-file docstring for the current signature — do not
memorize flags from this doc, they may change.

`ship.sh` appends every successful ship to
`$VAULT_001/PROJECTS/no3d tools/ship-log.md`. That log is the audit trail
for "what shipped when" — consult it before inferring release history from
git tags.

---

## Node-tree editing conduct  [POLICY]

Rules for any agent editing geometry-node (or shader/compositor) trees in a
live Blender session:

- **Anything in the Add/Search node catalogue is a pre-existing node.**
  Native nodes (`Set Position`, `Attribute Statistic`, …) AND installed
  node-group assets / preset libraries (Erindale Toolkit, Node++, T3D GN
  Presets, CGMatter, Higgsas, project asset catalogues, etc.). Instancing
  one into a tree — even into a group the agent is designing — does not
  make it "newly created."
- **Never rename OR re-label pre-existing nodes.** An unlabeled functional
  node's header self-documents its operation (a Math node displays `Add` /
  `Multiply` as its title). A custom label OVERRIDES that header — a
  Multiply labeled `Combine` or an Add labeled `CALC` actively hides the
  operation and forces the reader to open every node to follow the logic.
  The label isn't just noise; it's disinformation. Auto `.001` suffixes
  stay too.
  - **Exception — input/constant nodes** (Value, Integer, Vector, Boolean,
    and similar Input-category nodes whose only job is to supply a value):
    these MAY be labeled to state what the value represents (e.g. a Value
    node labeled `rest length`). Their generic catalogue name conveys
    nothing; the label is the readable part.
- **Annotation goes in labeled frames, not node names or labels.** If the
  goal is to label, comment, or explain a region of logic, wrap the nodes
  in a **frame** and label the frame. Frames are the designated commentary
  layer.
- **The only thing an agent ever names is a newly *designed* node group
  asset.** A group the agent authors in-session gets a descriptive name at
  creation time (e.g. `Connect: MST`). That is the entire naming surface —
  nothing inside it, nothing pre-existing.

---

## Anti-patterns  [POLICY]

Do NOT:

- Hardcode `~/Projects/no3d-asset-developer` (or any absolute path) into
  new code. Read `resolve_anchors()` or the env vars.
- Pattern-match on the string `"no3d-asset-developer"` to identify the
  monorepo. Detect it as "the directory under `$NO3D_PROJECTS_ROOT`
  containing both `vendor.toml` and `extensions/`" instead — future-proof
  against renames.
- Edit inside `$NO3D_MONOREPO/extensions/<vendored-id>/`. `vendor_sync.sh`
  will overwrite you.
- Silently update this file if you spot it's out of date. Commit the
  correction with a note explaining what changed and when — future
  sessions read git history to understand the ecosystem's evolution.
- Assume `git status` is clean without running it. Assume the installed
  copy of any add-on matches its source without diffing.

---

## Handoff for future Claude  [POLICY]

If, at session end, you know something about the ecosystem that isn't
captured here and would help the next session — **write it down**. Options:

- Add it as a `[POLICY]` bullet under an existing section here.
- If it's project-specific, write it to the project's own `CLAUDE.md`
  instead (project tier).
- If it's a machine-detectable fact rather than a policy, add discovery
  logic to `discover_addon_repos` / `discover_blend_projects` /
  `_asset_libraries` so future sessions get it automatically via
  **Refresh Drift Map**.

Prefer growing the discovery over growing the enumeration. Every static
list in this file is a future drift bug.
