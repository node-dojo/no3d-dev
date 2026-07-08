# Merge Claude Pair + Save & Reload into No3d Asset Developer

**Date:** 2026-07-08
**Target repo:** `/Users/joebowers/Projects/no3d-asset-developer` → `github.com/node-dojo/no3d-asset-developer`
**Version bump:** 3.1.0 → 3.2.0

## Goal

Fold two standalone Blender add-ons into the No3d Asset Developer extension as first-class
feature modules, matching the host's existing modular pattern (self-contained subpackage/module
with `register()`/`unregister()`, wired in `__init__.py`, listed in `blender_manifest.toml`
build paths). Then commit and push to the `node-dojo/no3d-asset-developer` remote.

### Source add-ons

1. **Claude Pair** — `<The Well Code>/claude_pair/` (`__init__.py`, `pair.py`, `registry.py`).
   Pairs a Blender instance with a Claude Code terminal session over the official MCP add-on.
   Own "Claude" N-panel tab, two keymaps (Reveal / Agentic Layout), a `load_post` handler.
2. **Save & Reload** — `~/Library/verge3d_blender/addons/save_and_reload/`
   (`save_op.py`, `preferences.py`, `helper.py`). Saves the current .blend as the next
   iteration (`.001`, `.002`, …) then quits + relaunches this Blender instance. macOS only.
   File-menu entry + Cmd+Shift+R keymap.

Both source add-ons are structurally clean and self-contained. This is a mechanical merge,
not a rewrite.

## Architecture

Each add-on becomes a subpackage under the host, imported and register()-ordered in
`__init__.py`, exactly like the existing `wip/` and `notes/` subpackages.

```
no3d-asset-developer/
  claude_pair/
    __init__.py      # module (NOT an add-on entrypoint) — panel, operators, keymaps, load_post
    pair.py          # copied verbatim (self-contained: only imports bpy, socket, subprocess)
    registry.py      # copied verbatim (self-contained: only imports json, os, time)
  save_reload/
    __init__.py      # exposes register()/unregister() over save_op
    save_op.py       # operator + File-menu entry + Cmd+Shift+R keymap
    helper.py        # detached relaunch helper (system python3, not Blender's)
```

### The AddonPreferences problem

A nested module **cannot own a second `AddonPreferences`** — Blender allows exactly one
`AddonPreferences` per registered add-on, keyed by the add-on's top-level package name. Both
source add-ons define their own. Resolution:

- **Fold their preference properties into the host's `NO3D_AddonPreferences`** (in the host
  `__init__.py`), grouped under labeled boxes in `draw()`:
  - Save & Reload: `save_folder`, `iteration_digits`, `confirm_before_restart`
  - Claude Pair: `scratch_dir`, `claude_command`, `claude_extra_args`, `claude_auto_start`,
    `auto_write_permissions`, `mcp_host`, `port_range_start`, `port_range_end`,
    `start_server_on_load`, `iterm_open_as`, `iterm_profile`, `verbose_logging`
- **Rewrite each module's `get_prefs()` / `_prefs()`** to read the host add-on's prefs
  (`context.preferences.addons[<host package>].preferences`) instead of their own.
  The host package name is available to submodules as `__package__.split(".")[0]` or by
  importing a shared constant.

### What gets dropped

From Claude Pair, the standalone-only maintenance operators **do not carry over** — they
disable/remove the *host* add-on, which is nonsensical when Claude Pair is a sub-feature:
- `CLAUDE_PAIR_OT_reload` (reloads the standalone add-on)
- `CLAUDE_PAIR_OT_uninstall` (removes the standalone add-on)

Their two buttons are removed from the folded preferences UI. Everything else (Pair Now,
Re-pair & Resume, New Session, Reveal, Agentic Layout, Unpair, diagnostics, doc editors,
permissions dropper) carries over unchanged.

## UI placement

- **Claude Pair** keeps its own dedicated **"Claude"** N-panel tab (`bl_category = "Claude"`),
  exactly as standalone. Deliberately separate from the "No3D Dev" tab.
- **Save & Reload** keeps its **File menu** entry ("Save and Reload", near Save As) — no
  N-panel presence. Cmd+Shift+R keymap preserved.
- Both add-ons' preferences render as new labeled boxes on the single host preferences page.

## Registration wiring (`__init__.py`)

New imports alongside the existing module imports:
```python
from . import claude_pair
from . import save_reload
```

`register()` — append after the existing feature modules:
```python
    save_reload.register()
    claude_pair.register()
```
`unregister()` — prepend in reverse (LIFO), before the existing teardown:
```python
    claude_pair.unregister()
    save_reload.unregister()
```

Ordering note: the folded preference *properties* live on `NO3D_AddonPreferences`, which
registers early (before `_register_wm_props()`), so both modules can read prefs at their
own register time. No cross-module property ownership (unlike `aspect_overlay`), so no
special early/late ordering is required beyond registering the modules after prefs exist.

## Manifest (`blender_manifest.toml`)

- Bump `version` to `3.2.0`.
- Add build paths:
  ```
  "claude_pair/__init__.py",
  "claude_pair/pair.py",
  "claude_pair/registry.py",
  "save_reload/__init__.py",
  "save_reload/save_op.py",
  "save_reload/helper.py",
  ```
- **Permissions:** Claude Pair's manifest declared `network` ("Coordinates with the official
  MCP add-on") and `files`. The host already declares `files`. Add a `network` permission
  reason to the host manifest's `[permissions]` block, since Claude Pair configures/starts
  the official MCP bridge server (localhost TCP).
- Bump `bl_info["version"]` in `__init__.py` to `(3, 2, 0)` to match.

## Constraints & platform notes

- **macOS only** for Save & Reload (spawns `open -n -a`) and Claude Pair (iTerm2 AppleScript).
  The host already targets Joe's Mac workflow; no cross-platform guard added. Both fail
  gracefully with an operator `report({"ERROR"}, …)` off-platform rather than crashing.
- **External dependency:** Claude Pair coordinates with the **official Blender Lab MCP add-on**
  (`bl_ext.lab_blender_org.mcp`) which must be installed and enabled separately. Claude Pair's
  operators already surface a clean error if it's missing (`official_mcp_prefs()` raises →
  caught → reported). This is unchanged by the merge.
- `blender_version_min`: host is `5.0.0`; Claude Pair's standalone manifest said `5.1.0`.
  Keep the host's `5.0.0` — Claude Pair's pairing operators degrade gracefully and the
  N-panel is harmless on 5.0. (Joe's paired instances run 5.1+ in practice.)

## Discoverability / anti-confusion (per Joe's request)

There are **stale duplicate copies** of the asset-developer add-on under
`<The Well Code>/solvet-global/no3d-asset-developer/` and
`<The Well Code>/no3d-asset-developer_v2.zip` etc. These push to the OLD remote
`node-dojo/no3d-tools-addon.git`. The canonical, up-to-date repo is
`/Users/joebowers/Projects/no3d-asset-developer` → `node-dojo/no3d-asset-developer.git`.

To keep future agents from editing the stale copy, drop a `STALE_DO_NOT_EDIT.md` pointer
note into `solvet-global/no3d-asset-developer/` (and any other stale copy found) that points
to the canonical repo. This is a documentation-only side task, committed nowhere (the stale
copies are separate git repos) — the note just lives on disk as a breadcrumb.

## Testing / verification

No unit-test harness in this repo. Verification is by loading the built extension in Blender:
1. Build the extension (`.zip`) and install into Blender 5.x.
2. Confirm the add-on enables without a registration error (the prefs-ordering trap).
3. Confirm three UI surfaces appear: "Claude" N-panel tab, "Save and Reload" File-menu entry,
   and the folded preference boxes on the add-on prefs page.
4. Smoke-test Save & Reload on a saved throwaway .blend (it relaunches Blender — do last).
5. Smoke-test Claude Pair "Pair Now" if the official MCP add-on is present.

Steps 1–3 are the register-integrity gate and must pass before commit. Steps 4–5 are
live-behavior checks Joe runs interactively.

## Out of scope

- No refactor of the existing host modules.
- No cross-platform (Windows/Linux) support for the two new features.
- No change to the official MCP add-on or its installation.
- No deletion of the stale duplicate copies (only breadcrumb notes).
