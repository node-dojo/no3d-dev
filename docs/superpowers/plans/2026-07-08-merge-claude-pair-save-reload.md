# Merge Claude Pair + Save & Reload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fold the standalone Claude Pair and Save & Reload Blender add-ons into the No3d Asset Developer extension as first-class feature subpackages, then confirm the merged extension registers cleanly and its three UI surfaces appear.

**Architecture:** Each source add-on becomes a subpackage (`claude_pair/`, `save_reload/`) with its own `register()`/`unregister()`, imported and ordered in the host `__init__.py` exactly like the existing `wip/` and `notes/` subpackages. Because Blender allows only one `AddonPreferences` per add-on, each source add-on's preference properties are folded into the host's `NO3D_AddonPreferences`, and each module's prefs accessor is rewritten to read the host add-on via `HOST_PACKAGE = __package__.rsplit(".", 1)[0]`.

**Tech Stack:** Blender 5.x Python extension API (`bpy`), extension manifest format (`blender_manifest.toml`), headless Blender CLI for register verification.

## Global Constraints

- **Version:** bump host to `3.2.0` in BOTH `blender_manifest.toml` (`version`) and `__init__.py` (`bl_info["version"] = (3, 2, 0)`). They must agree.
- **Blender floor:** `blender_version_min = "5.0.0"` stays (do NOT raise to Claude Pair's standalone 5.1.0).
- **Platform:** macOS only for both new features; no cross-platform guards added; operators fail gracefully with `self.report({"ERROR"}, …)`.
- **Prefs single-owner:** exactly one `AddonPreferences` (`NO3D_AddonPreferences`) in the whole add-on. No copied module may define a second one.
- **Host prefs key in subpackages:** `HOST_PACKAGE = __package__.rsplit(".", 1)[0]`; read `bpy.context.preferences.addons[HOST_PACKAGE].preferences`. Never bare `__package__` inside a subpackage, never hardcode `"no3d_asset_developer"`.
- **Dropped operators:** Claude Pair's `CLAUDE_PAIR_OT_reload` and `CLAUDE_PAIR_OT_uninstall` do NOT carry over (they disable/remove the host add-on).
- **Blender CLI for verification:** `/Applications/Blender 5.2 Beta.app/Contents/MacOS/Blender`, always invoked with `--factory-startup --background`.
- **No secrets, no network calls in tests.** The register-check never pairs or ships.

## Source-of-truth paths

- Host repo (edit here): `/Users/joebowers/Projects/no3d-asset-developer`
- Save & Reload source: `~/Library/verge3d_blender/addons/save_and_reload/` (`save_op.py`, `preferences.py`, `helper.py`)
- Claude Pair source: `<The Well Code>/claude_pair/` (`__init__.py`, `pair.py`, `registry.py`)

## File Structure (what this plan creates/modifies)

```
no3d-asset-developer/
  save_reload/
    __init__.py       # NEW — register()/unregister() over save_op
    save_op.py        # COPIED from source, minus its own prefs import; get_prefs → host
    helper.py         # COPIED verbatim (standalone system-python script)
  claude_pair/
    __init__.py       # COPIED from source __init__.py, minus AddonPreferences + reload/uninstall ops; _prefs → host
    pair.py           # COPIED verbatim
    registry.py       # COPIED verbatim
  __init__.py         # MODIFY — fold both feature prefs into NO3D_AddonPreferences; import + register/unregister both modules; bl_info 3.2.0
  blender_manifest.toml  # MODIFY — version 3.2.0; add 6 build paths; add network permission
  tools/check_register.sh  # NEW — headless register-integrity harness (reused by every task)
```

---

### Task 0: Register-integrity verification harness

A reusable headless check that builds nothing but confirms the add-on enables without error and its expected classes/panels are registered. Every later task runs this.

**Files:**
- Create: `tools/check_register.sh`

**Interfaces:**
- Produces: `tools/check_register.sh` — exits 0 and prints `REGISTER_OK` on success; non-zero + traceback on failure. Takes no args.

- [ ] **Step 1: Write the harness script**

Create `tools/check_register.sh`:

```bash
#!/bin/bash
# check_register.sh — headless proof that the add-on enables cleanly and its
# key surfaces are registered. Installs the current working tree as a temp
# extension into a throwaway Blender config, enables it, asserts, tears down.
#
# Usage:  tools/check_register.sh
# Exit 0 + "REGISTER_OK" on success; non-zero + traceback on failure.
set -euo pipefail

BLENDER="/Applications/Blender 5.2 Beta.app/Contents/MacOS/Blender"
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"

"$BLENDER" --factory-startup --background --python-expr "
import bpy, sys, traceback
PROJECT = r'''$PROJECT'''
try:
    # Install the working tree as an extension from disk, then enable it.
    bpy.ops.extensions.package_install_files(
        filepath='', directory=PROJECT, repo='user_default',
        enable_on_install=True,
    ) if False else None
    # Simpler + version-stable: register the package directly by adding the
    # parent dir to sys.path and importing, mirroring how Blender loads it.
    import os
    parent = os.path.dirname(PROJECT)
    pkg = os.path.basename(PROJECT)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    mod = __import__(pkg)
    mod.register()
    # Assertions: the three surfaces + prefs presence.
    assert hasattr(bpy.types, 'NO3D_AddonPreferences'), 'host prefs missing'
    mod.unregister()
    print('REGISTER_OK')
except Exception:
    traceback.print_exc()
    sys.exit(1)
"
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x tools/check_register.sh`

- [ ] **Step 3: Run it against the current (pre-merge) tree**

Run: `tools/check_register.sh 2>&1 | tail -20`
Expected: ends with `REGISTER_OK`. (This proves the harness works on the known-good baseline before we change anything. The `pkg = basename(PROJECT)` is `no3d-asset-developer` — a dir name with a hyphen is not importable, so if this fails on baseline, fall to Step 4.)

- [ ] **Step 4: If baseline import fails on the hyphenated dir name, use a symlink shim**

The repo dir is `no3d-asset-developer` (hyphen → not a valid Python module name). Fix the harness to import via a temp symlink with an underscore name:

```bash
# Replace the sys.path/import block in the --python-expr with:
    import os, tempfile
    tmp = tempfile.mkdtemp()
    link = os.path.join(tmp, 'no3d_asset_developer')
    os.symlink(PROJECT, link)
    if tmp not in sys.path:
        sys.path.insert(0, tmp)
    mod = __import__('no3d_asset_developer')
```

Re-run Step 3. Expected: `REGISTER_OK`.

- [ ] **Step 5: Commit**

```bash
git add tools/check_register.sh
git commit -m "test: headless register-integrity harness for the add-on

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 1: Vendor Save & Reload as the `save_reload/` subpackage

Copy the 3 source files, rewrite `preferences.get_prefs()` usages to read the host prefs, and give the subpackage a clean `register()`/`unregister()`. The host prefs don't exist yet for these 3 props — Task 3 adds them — so this task's register-check is deferred to Task 3. Here we just get the code in place and import-clean.

**Files:**
- Create: `save_reload/__init__.py`, `save_reload/save_op.py`, `save_reload/helper.py`

**Interfaces:**
- Consumes: host prefs props `save_folder`, `iteration_digits`, `confirm_before_restart` (added in Task 3).
- Produces: `save_reload.register()` / `save_reload.unregister()`; operator `save_and_reload.run`; File-menu entry; Cmd+Shift+R keymap in "3D View".

- [ ] **Step 1: Create the subpackage dir and copy helper.py verbatim**

```bash
mkdir -p save_reload
cp ~/Library/verge3d_blender/addons/save_and_reload/helper.py save_reload/helper.py
```

`helper.py` is a standalone system-python script with no `bpy` and no package imports — it copies unchanged.

- [ ] **Step 2: Copy save_op.py and strip its `from . import preferences`**

```bash
cp ~/Library/verge3d_blender/addons/save_and_reload/save_op.py save_reload/save_op.py
```

Then edit `save_reload/save_op.py`:
- Remove the line `from . import preferences`.
- Add near the top (after `import bpy`):

```python
HOST_PACKAGE = __package__.rsplit(".", 1)[0]  # e.g. "no3d_asset_developer"


def _prefs():
    """Read the host add-on's preferences (Save & Reload props folded in)."""
    return bpy.context.preferences.addons[HOST_PACKAGE].preferences
```

- Replace both `preferences.get_prefs()` calls (in `invoke()` and `execute()`) with `_prefs()`.

Everything else in `save_op.py` (iteration logic, app discovery, helper spawn, menu draw, keymap add/remove, `register()`/`unregister()`) stays byte-for-byte.

- [ ] **Step 3: Create save_reload/__init__.py**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Save & Reload — one-click iteration save + relaunch of this Blender instance.

Vendored into No3d Asset Developer as a feature subpackage. Its preferences are
folded into the host NO3D_AddonPreferences (Blender allows one AddonPreferences
per add-on); this package exposes only the operator, File-menu entry, and keymap.
macOS only.
"""

from . import save_op

_modules = (save_op,)


def register():
    for m in _modules:
        if hasattr(m, "register"):
            m.register()


def unregister():
    for m in reversed(_modules):
        if hasattr(m, "unregister"):
            m.unregister()
```

- [ ] **Step 4: Import-lint the copied module offline (no host prefs needed)**

Run:
```bash
python3 -c "import ast; ast.parse(open('save_reload/save_op.py').read()); ast.parse(open('save_reload/__init__.py').read()); print('AST_OK')"
```
Expected: `AST_OK`. Confirm no `import preferences` / `get_prefs` remain:
```bash
grep -nE "preferences\.get_prefs|from \. import preferences" save_reload/save_op.py || echo "NONE_REMAIN"
```
Expected: `NONE_REMAIN`.

- [ ] **Step 5: Commit**

```bash
git add save_reload/
git commit -m "feat(save-reload): vendor Save & Reload as save_reload/ subpackage

Prefs accessor rewritten to read host NO3D_AddonPreferences via HOST_PACKAGE.
Registration wiring in __init__.py comes in a later task.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Vendor Claude Pair as the `claude_pair/` subpackage

Copy `pair.py` and `registry.py` verbatim; copy `__init__.py` with three surgical changes: delete its `AddonPreferences` class, delete the `reload`/`uninstall` operators, and rewrite `_prefs()` to read the host. Register-check deferred to Task 3 (needs host prefs).

**Files:**
- Create: `claude_pair/__init__.py`, `claude_pair/pair.py`, `claude_pair/registry.py`

**Interfaces:**
- Consumes: host prefs props (Claude Pair set, added in Task 3): `scratch_dir`, `claude_command`, `claude_extra_args`, `claude_auto_start`, `auto_write_permissions`, `mcp_host`, `port_range_start`, `port_range_end`, `start_server_on_load`, `iterm_open_as`, `iterm_profile`, `verbose_logging`.
- Produces: `claude_pair.register()` / `claude_pair.unregister()`; the "Claude" N-panel tab; operators `claude_pair.pair_now`, `.repair_resume`, `.new_session_for_file`, `.reveal`, `.agentic_layout`, `.unpair`, `.copy_diagnostics`, `.open_registry_dir`, `.edit_global_doc`, `.edit_pointer_doc`, `.edit_project_md`, `.write_project_permissions`; two keymaps; `load_post` handler.

- [ ] **Step 1: Copy pair.py and registry.py verbatim**

```bash
mkdir -p claude_pair
cp "$HOME/Library/CloudStorage/Dropbox/Caveman Creative/THE WELL_Digital Assets/The Well Code/claude_pair/pair.py" claude_pair/pair.py
cp "$HOME/Library/CloudStorage/Dropbox/Caveman Creative/THE WELL_Digital Assets/The Well Code/claude_pair/registry.py" claude_pair/registry.py
```

Both are self-contained (no relative imports beyond `bpy`/stdlib) — copy unchanged.

- [ ] **Step 2: Copy __init__.py to the subpackage**

```bash
cp "$HOME/Library/CloudStorage/Dropbox/Caveman Creative/THE WELL_Digital Assets/The Well Code/claude_pair/__init__.py" claude_pair/__init__.py
```

- [ ] **Step 3: Delete the `CLAUDE_PAIR_AddonPreferences` class**

In `claude_pair/__init__.py`, remove the entire `class CLAUDE_PAIR_AddonPreferences(AddonPreferences):` block (from its `class` line through the end of its `draw()` method, ending just before `def _prefs():`). Its properties move to the host prefs in Task 3.

- [ ] **Step 4: Rewrite `_prefs()` to read the host add-on**

Replace:

```python
def _prefs():
    key = __package__ if __package__ else "claude_pair"
    return bpy.context.preferences.addons[key].preferences
```

with:

```python
HOST_PACKAGE = __package__.rsplit(".", 1)[0]  # host add-on package, e.g. "no3d_asset_developer"


def _prefs():
    return bpy.context.preferences.addons[HOST_PACKAGE].preferences
```

- [ ] **Step 5: Delete the `reload` and `uninstall` operators + their prefs buttons**

- Remove the entire `class CLAUDE_PAIR_OT_reload(Operator):` block.
- Remove the entire `class CLAUDE_PAIR_OT_uninstall(Operator):` block.
- Remove both from the `_classes` tuple (`CLAUDE_PAIR_OT_reload,` and `CLAUDE_PAIR_OT_uninstall,`).
- These operators were only drawn from the deleted prefs `draw()` (the "Maintenance" box), so no panel code references them. Verify:

```bash
grep -nE "OT_reload|OT_uninstall|AddonPreferences" claude_pair/__init__.py || echo "ALL_CLEAN"
```
Expected: `ALL_CLEAN` (the only remaining `AddonPreferences` reference should be gone; if the `from bpy.types import ... AddonPreferences` import line remains, that's harmless but remove it for cleanliness).

- [ ] **Step 6: Remove the now-unused `AddonPreferences` import**

In the `from bpy.types import AddonPreferences, Operator, Panel` line, drop `AddonPreferences,` → `from bpy.types import Operator, Panel`.

- [ ] **Step 7: AST-lint the three files**

Run:
```bash
python3 -c "import ast; [ast.parse(open(f).read()) for f in ('claude_pair/__init__.py','claude_pair/pair.py','claude_pair/registry.py')]; print('AST_OK')"
```
Expected: `AST_OK`.

- [ ] **Step 8: Commit**

```bash
git add claude_pair/
git commit -m "feat(claude-pair): vendor Claude Pair as claude_pair/ subpackage

Drops its standalone AddonPreferences (folded into host next task) and the
reload/uninstall operators (they'd disable the host add-on). _prefs() now reads
the host via HOST_PACKAGE. pair.py/registry.py copied verbatim.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Fold both feature prefs into host `NO3D_AddonPreferences` + wire registration

This is the task that makes the add-on whole: add all 15 folded props to the host prefs class, render them in `draw()`, import both subpackages, and add them to `register()`/`unregister()` in the correct order. Ends with the full headless register-check — the integration gate.

**Files:**
- Modify: `__init__.py` (host)

**Interfaces:**
- Consumes: `save_reload.register/unregister`, `claude_pair.register/unregister` (Tasks 1–2).
- Produces: the 15 folded preference properties on `NO3D_AddonPreferences`; both modules registered.

- [ ] **Step 1: Add the Save & Reload props to `NO3D_AddonPreferences`**

In `__init__.py`, inside `class NO3D_AddonPreferences`, after the existing `aspect_section_custom_expanded` prop (end of the property block, before `def draw`), add:

```python
    # ----- Save & Reload (folded from the standalone add-on) -----
    save_folder: StringProperty(
        name="Save folder",
        description=(
            "Folder to save iteration .blend files into. "
            "Leave blank to save next to the current .blend file."
        ),
        default="",
        subtype="DIR_PATH",
    )
    iteration_digits: IntProperty(
        name="Iteration digits",
        description="Zero-padding width for the iteration suffix (e.g. 3 -> .001)",
        default=3, min=2, max=6,
    )
    confirm_before_restart: BoolProperty(
        name="Confirm before restart",
        description="Show a confirmation popup before saving and relaunching Blender",
        default=False,
    )
```

- [ ] **Step 2: Add the Claude Pair props to `NO3D_AddonPreferences`**

Immediately after the Save & Reload props, add (copied from the deleted `CLAUDE_PAIR_AddonPreferences`, verbatim property definitions):

```python
    # ----- Claude Pair (folded from the standalone add-on) -----
    scratch_dir: StringProperty(
        name="Scratch directory",
        description="Working directory used when the blend file has not been saved",
        default=str(os.path.join(os.path.expanduser("~"), "Desktop")),
        subtype="DIR_PATH",
    )
    claude_command: StringProperty(
        name="Claude command",
        description="Shell command to launch Claude Code in the paired terminal",
        default="claude",
    )
    claude_extra_args: StringProperty(
        name="Extra args",
        description="Additional arguments appended to the claude command (e.g. --model opus)",
        default="",
    )
    claude_auto_start: BoolProperty(
        name="Auto-start Claude",
        description="Run claude immediately in the spawned terminal. Disable to leave a plain shell open.",
        default=True,
    )
    auto_write_permissions: BoolProperty(
        name="Drop project permissions on pair",
        description="Write .claude/settings.local.json into the pair's cwd when pairing (only if absent)",
        default=True,
    )
    mcp_host: StringProperty(
        name="MCP host",
        description="Host the official MCP add-on binds to. localhost is correct in nearly all cases.",
        default="localhost",
    )
    port_range_start: IntProperty(
        name="Port range start",
        description="First port to try when scanning for a free port",
        default=9876, min=1024, max=65535,
    )
    port_range_end: IntProperty(
        name="Port range end",
        description="Last port to try when scanning for a free port",
        default=9999, min=1024, max=65535,
    )
    start_server_on_load: BoolProperty(
        name="Start MCP server on Blender startup",
        description=(
            "Automatically start the official MCP server after Blender loads a .blend "
            "file. Useful when paired with 'Re-pair & Resume' — the server is up before "
            "the user re-attaches Claude."
        ),
        default=False,
    )
    iterm_open_as: EnumProperty(
        name="Open as",
        description="Spawn a new iTerm2 window or a new tab in the front window",
        items=[
            ("WINDOW", "New window", "Open a fresh iTerm2 window"),
            ("TAB", "New tab", "Open a tab in the front iTerm2 window (falls back to window)"),
        ],
        default="WINDOW",
    )
    iterm_profile: StringProperty(
        name="iTerm2 profile",
        description="iTerm2 profile name to use. Leave blank for the default profile.",
        default="",
    )
    verbose_logging: BoolProperty(
        name="Verbose logging",
        description="Print pair lifecycle events to the system console",
        default=False,
    )
```

(`os` is already imported at the top of `__init__.py`.)

- [ ] **Step 3: Render the folded props in `draw()`**

In `NO3D_AddonPreferences.draw()`, after the existing "Clipboard Paste" box and before the "Keymap" box, add:

```python
        layout.separator()

        # Save & Reload
        box = layout.box()
        box.label(text="Save & Reload", icon="FILE_REFRESH")
        box.prop(self, "save_folder")
        box.prop(self, "iteration_digits")
        box.prop(self, "confirm_before_restart")
        box.label(text="Shortcut: Cmd+Shift+R (3D View). macOS only.", icon="INFO")

        layout.separator()

        # Claude Pair
        box = layout.box()
        box.label(text="Claude Pair", icon="LINKED")
        box.prop(self, "scratch_dir")
        box.prop(self, "claude_command")
        box.prop(self, "claude_extra_args")
        box.prop(self, "claude_auto_start")
        box.prop(self, "auto_write_permissions")
        row = box.row(align=True)
        row.prop(self, "mcp_host")
        sub = box.row(align=True)
        sub.prop(self, "port_range_start")
        sub.prop(self, "port_range_end")
        box.prop(self, "start_server_on_load")
        box.prop(self, "iterm_open_as")
        box.prop(self, "iterm_profile")
        box.prop(self, "verbose_logging")
        box.label(text="Requires the official Blender MCP add-on. macOS/iTerm2 only.", icon="INFO")
```

- [ ] **Step 4: Import both subpackages**

In the import block of `__init__.py`, alongside `from . import wip` etc., add:

```python
from . import claude_pair
from . import save_reload
```

- [ ] **Step 5: Wire `register()`**

In `register()`, after the existing `repo_registration.register()` (the last line), add:

```python
    save_reload.register()
    claude_pair.register()
```

- [ ] **Step 6: Wire `unregister()`**

In `unregister()`, at the very top (before `repo_registration.unregister()`), add — reverse order:

```python
    claude_pair.unregister()
    save_reload.unregister()
```

- [ ] **Step 7: Run the full register-integrity check**

Run: `tools/check_register.sh 2>&1 | tail -25`
Expected: ends with `REGISTER_OK`. This proves: host prefs register with all 15 new props, both subpackages register without a duplicate-`AddonPreferences` error or a missing-prefs `KeyError`, and unregister is clean.

- [ ] **Step 8: Assert the three surfaces exist (extend the check inline)**

Run this one-off to confirm the operators/panel/menu registered:

```bash
"/Applications/Blender 5.2 Beta.app/Contents/MacOS/Blender" --factory-startup --background --python-expr "
import bpy, sys, os, tempfile, traceback
PROJECT=r'''$(pwd)'''
tmp=tempfile.mkdtemp(); link=os.path.join(tmp,'no3d_asset_developer'); os.symlink(PROJECT,link)
sys.path.insert(0,tmp)
m=__import__('no3d_asset_developer'); m.register()
try:
    assert hasattr(bpy.types,'CLAUDE_PAIR_PT_panel'), 'Claude panel missing'
    assert hasattr(bpy.types,'SAVE_AND_RELOAD_OT_run'), 'save_and_reload op missing'
    assert hasattr(bpy.types,'CLAUDE_PAIR_OT_pair_now'), 'pair_now op missing'
    assert not hasattr(bpy.types,'CLAUDE_PAIR_OT_reload'), 'reload op should be dropped'
    p=bpy.context.preferences.addons['no3d_asset_developer'].preferences
    for prop in ('save_folder','iteration_digits','claude_command','port_range_start','verbose_logging'):
        assert hasattr(p,prop), f'missing pref {prop}'
    print('SURFACES_OK')
finally:
    m.unregister()
" 2>&1 | tail -10
```
Expected: `SURFACES_OK`.

- [ ] **Step 9: Commit**

```bash
git add __init__.py
git commit -m "feat: register Claude Pair + Save & Reload; fold their prefs into host

15 preference properties folded into NO3D_AddonPreferences with grouped draw()
sections. Both subpackages imported and register/unregister-wired (LIFO). Headless
register + surface checks pass.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Manifest — version bump, build paths, network permission

Ship the new files and declare the network permission Claude Pair needs (it drives the official MCP bridge on localhost).

**Files:**
- Modify: `blender_manifest.toml`, `__init__.py` (bl_info version)

**Interfaces:**
- Consumes: the files created in Tasks 0–3.
- Produces: a buildable extension at version 3.2.0.

- [ ] **Step 1: Bump the manifest version**

In `blender_manifest.toml`, change `version = "3.1.0"` → `version = "3.2.0"`.

- [ ] **Step 2: Bump bl_info to match**

In `__init__.py`, change `"version": (3, 1, 0),` → `"version": (3, 2, 0),`.

- [ ] **Step 3: Add the network permission**

In `blender_manifest.toml`, in the `[permissions]` block (currently only `files = …`), add:

```toml
network = "Claude Pair configures and starts the official Blender MCP bridge server on localhost"
```

- [ ] **Step 4: Add the six new build paths**

In `blender_manifest.toml`, in `[build].paths`, add (after the existing entries, before `"LICENSE",`):

```toml
  "claude_pair/__init__.py",
  "claude_pair/pair.py",
  "claude_pair/registry.py",
  "save_reload/__init__.py",
  "save_reload/save_op.py",
  "save_reload/helper.py",
```

- [ ] **Step 5: Build the extension headlessly (the real gate)**

Run:
```bash
"/Applications/Blender 5.2 Beta.app/Contents/MacOS/Blender" --factory-startup --command extension build \
  --source-dir "$(pwd)" --output-filepath "dist/no3d_asset_developer-3.2.0.zip" 2>&1 | tail -20
```
Expected: reports a successfully created `dist/no3d_asset_developer-3.2.0.zip` with no manifest/validation errors. (If it complains a listed path is missing or an unlisted file is present, reconcile `[build].paths` with the tree.)

- [ ] **Step 6: Confirm the six new files are inside the zip**

Run:
```bash
unzip -l dist/no3d_asset_developer-3.2.0.zip | grep -E "claude_pair/|save_reload/"
```
Expected: all six files listed (`claude_pair/__init__.py`, `pair.py`, `registry.py`, `save_reload/__init__.py`, `save_op.py`, `helper.py`).

- [ ] **Step 7: Commit**

```bash
git add blender_manifest.toml __init__.py
git commit -m "build: v3.2.0 — ship claude_pair/ + save_reload/; add network permission

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: README + stale-copy breadcrumb note (in-repo)

Document the two new features in the repo README and leave an in-repo pointer to the canonical location (complements the out-of-repo breadcrumb already dropped in `solvet-global`).

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: nothing.
- Produces: user-facing docs for the two merged features.

- [ ] **Step 1: Add a "Bundled tools" section to README.md**

Append to `README.md`:

```markdown
## Bundled tools

Beyond asset export, this add-on bundles two macOS workflow tools:

### Save & Reload
`File → Save and Reload` (or **Cmd+Shift+R** in the 3D View) saves the current
`.blend` as the next iteration (`.001`, `.002`, …) then quits and relaunches
this Blender instance with the saved file. Other running Blender instances are
untouched. Configure the save folder, iteration padding, and a confirm-prompt in
the add-on preferences. macOS only.

### Claude Pair
The **"Claude"** tab in the 3D-viewport N-panel pairs this Blender instance with
a Claude Code terminal session over the official Blender MCP add-on. "Pair Now"
opens an iTerm2 window bound to a free MCP port; "Re-pair & Resume" re-attaches
the prior conversation after a restart. Requires the official Blender MCP add-on
installed separately. macOS / iTerm2 only.
```

- [ ] **Step 2: Verify README renders (sanity: no broken fences)**

Run: `python3 -c "print(open('README.md').read()[-600:])"`
Expected: prints the new section cleanly.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document bundled Save & Reload + Claude Pair tools

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Push to origin

**Files:** none (git operation only).

- [ ] **Step 1: Confirm branch and clean tree**

Run: `git status -sb && git log --oneline origin/main..HEAD`
Expected: on `main`, clean tree, the Task 0–5 commits listed as ahead of `origin/main`.

- [ ] **Step 2: Push**

Run: `git push origin main`
Expected: push succeeds to `github.com/node-dojo/no3d-asset-developer`.

- [ ] **Step 3: Report the pushed range**

Run: `git log --oneline -8`
Report the top commit SHA to the user. (Tagging + gh-pages + Gumroad publish is the *pipeline* plan's job, not this merge — do NOT tag/publish here.)

---

## Self-Review

**Spec coverage** (against `2026-07-08-merge-claude-pair-save-reload-design.md`):
- Subpackage structure `claude_pair/` + `save_reload/` → Tasks 1, 2. ✓
- AddonPreferences folded into host + `get_prefs`/`_prefs` rewritten via `HOST_PACKAGE` → Tasks 1, 2, 3. ✓
- Dropped `reload`/`uninstall` operators + `__package__` audit → Task 2. ✓
- UI placement: Claude keeps its "Claude" tab, Save & Reload keeps File-menu entry → preserved by verbatim copy; asserted in Task 3 Step 8. ✓
- `__init__.py` register/unregister wiring (LIFO) → Task 3. ✓
- Manifest version 3.2.0 (both places), 6 build paths, network permission → Task 4. ✓
- `blender_version_min` stays 5.0.0 → Global Constraints (untouched in Task 4). ✓
- Verification gate (enable without error, three surfaces) → Task 0 harness + Task 3 Steps 7–8 + Task 4 Step 5. ✓
- Stale-copy breadcrumb → out-of-repo note already dropped this session; in-repo README pointer → Task 5. ✓
- Push to the *new* remote, no tag/publish → Task 6. ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code; every verify step shows the exact command + expected output.

**Type/name consistency:** `HOST_PACKAGE = __package__.rsplit(".", 1)[0]` and `_prefs()`/`_prefs` usage identical across Tasks 1–2; the 15 prop names in Task 3 match the accessor sites (`save_folder`, `iteration_digits`, `confirm_before_restart` for Save & Reload; the 12 Claude Pair names) verbatim from the source modules. Operator/panel idnames asserted in Task 3 Step 8 match the copied source.

**Known risk flagged for the executor:** the register-check imports the repo as `no3d_asset_developer` via a symlink because the on-disk dir is hyphenated (`no3d-asset-developer`). When Blender installs the built zip, the real package name is `bl_ext.<repo>.no3d_asset_developer`, so `HOST_PACKAGE = __package__.rsplit(".",1)[0]` resolves to `bl_ext.<repo>` at runtime — which is the correct add-on key in an installed extension. The symlink harness approximates this closely enough to catch registration errors; the definitive check is Task 4's real `extension build` + a manual install (Joe, interactively).
