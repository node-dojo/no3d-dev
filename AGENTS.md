# AGENTS.md

Entry point for AI agents (Cowork, Claude Code, Claude Pair, or any future
agent) landing in this repo. Read this before touching code. If you see
"CLAUDE.md" referenced anywhere in tooling, treat this file as the source of
truth — it applies to all agents, not just Claude.

## What this is

Blender **extension** (not a plain Python package). Distributed two ways:

- As a zipped extension on Gumroad — product id `MF2z7ZAjY-W9p4b_KOLjvw==`
- As a self-hosted extension repo at `node-dojo.github.io/no3d-asset-developer/index.json`

Both remote Blender installs (home + work Macs) subscribe to the extension
repo via `repo_registration.py` and auto-pull updates.

## Non-negotiables (read before editing)

- **One `AddonPreferences` for the whole add-on.** The host class is
  `NO3D_AddonPreferences` in `__init__.py`. Subpackages MUST read prefs via
  `HOST_PACKAGE = __package__.rsplit(".", 1)[0]` and
  `bpy.context.preferences.addons[HOST_PACKAGE].preferences` — never define
  a second `AddonPreferences`, never bare `__package__` in a subpackage,
  never hardcode `"no3d_asset_developer"`.
- **After any registration-touching change, run `tools/check_register.sh`.**
  It must print `REGISTER_OK`. This is the gate.
- **Version discipline.** `blender_manifest.toml`'s `version` and
  `__init__.py`'s `bl_info["version"]` must agree. Bump both together, always.
- **Don't rebuild what's already working:**
  - `repo_registration.py` — work-Mac auto-pull leg
  - `tools/publish_repo.sh` — gh-pages distribution leg
  - The Supabase WIP-library publisher at `<The Well Code>/no3d-remote-publish/`
    is a *different* pipeline (ships asset `.blend` files, not add-on code) —
    do NOT conflate.
- **Platform: macOS only** for `save_reload/` and `claude_pair/` features. No
  cross-platform guards; operators fail gracefully via
  `self.report({"ERROR"}, …)`.

## Blender quirks / gotchas

- **Hyphenated repo dir isn't importable.** `no3d-asset-developer` isn't a
  valid Python module name. `check_register.sh` imports via a temp symlink to
  `no3d_asset_developer/`. Any new headless script that imports the package
  needs the same shim.
- **`AddonPreferences` subclasses are NOT exposed on `bpy.types`.** Reproduced
  outside this add-on with a throwaway class. `hasattr(bpy.types, 'NO3D_AddonPreferences')`
  is **always False and misleading** — use `NO3D_AddonPreferences.is_registered`.
  Operators and Panels DO appear on `bpy.types` after `register_class`; this
  quirk only bites for `AddonPreferences`.
- **Bare `mod.register()` doesn't populate `bpy.context.preferences.addons[key]`.**
  Blender's real addon-enable path is what registers the addon entry; a
  lightweight harness that only calls `register_class` on the prefs class
  won't. To check that a preference *property* is declared, read it from the
  class itself: `NO3D_AddonPreferences.bl_rna.properties['<name>']`, not
  through `bpy.context.preferences.addons[...]`.
- **Headless Blender + enabled user add-ons often hangs.** Learned the hard
  way. Any custom `--background --python …` run should start with
  `--factory-startup` (loads no user prefs, so no user-enabled add-ons come
  along) and register only what the harness needs. If you're launching
  Blender headlessly with the user's normal config, expect intermittent hangs
  where an add-on's `register()` opens a modal / touches the network / spawns
  a thread. Rule of thumb: **headless = --factory-startup + only-the-add-on-under-test**.
  This is why `check_register.sh` uses `--factory-startup` and directly
  `mod.register()`s only this add-on.
- **Blender binary path is env-overridable.** Default is
  `/Applications/Blender 5.2 Beta.app/Contents/MacOS/Blender`. Shell scripts
  should honor `${BLENDER:-<default>}` so machines with a stable Blender
  install (e.g. the work Mac when 5.2 goes stable) don't break.

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

## Ship pipeline (design in progress)

`docs/superpowers/specs/2026-07-08-ship-pipeline-design.md` describes the
deterministic `tools/ship.sh` spine (build → GitHub tag + gh-pages → Gumroad
upload → append to vault ship log). Not built yet. Once it exists, the flow
is: agent merges the feature, runs `tools/ship.sh --version X.Y.Z --notes …`.

Session logs live in the vault, not the repo:
`$VAULT_001/PROJECTS/no3d tools/ship-log.md`. Absolute dates only.

## Directory map

- `__init__.py` — host registration, `NO3D_AddonPreferences`, `bl_info`
- `operators.py`, `ui.py` — export operators + N-panel + Asset Browser menu
- `blender_manifest.toml` — extension manifest (version, build paths,
  permissions)
- `wip/`, `notes/`, `save_reload/`, `claude_pair/` — feature subpackages
- `extraction_methods.py`, `blend_export.py`, `_export_single_asset.py` —
  retained internal template-append pipeline (not UI-exposed; re-enable with
  `wm.no3d_extraction_method = 'TEMPLATE_APPEND'`)
- `repo_registration.py` — self-subscribe to the extension repo on load
- `tools/check_register.sh` — headless registration gate
- `tools/publish_repo.sh` — gh-pages distribution (works, do not rebuild)
- `docs/superpowers/{specs,plans}/` — design docs + implementation plans
- `.superpowers/sdd/` — active task briefs, reports, progress ledger

## Current state / getting oriented

```bash
git status && git branch --show-current
git log --oneline -10
cat .superpowers/sdd/progress.md  # what the current SDD run is on
```

## Lessons / gotchas (append here after corrections)

<!--
When you get corrected on something — by the user or by a broken assumption
in a plan/spec — write the durable lesson as a bullet here so the next agent
starts with your correction as its baseline. Keep bullets tight. Once a
lesson stabilizes, promote it into the section above (Blender quirks or
Non-negotiables) and remove it from this list.
-->

- Do not write `hasattr(bpy.types, 'NO3D_AddonPreferences')` — always False
  for `AddonPreferences` subclasses. Use `is_registered` (see Gotchas).
- Do not check prefs *props* via `bpy.context.preferences.addons[key]` in a
  bare-harness context — read them from `<PrefsClass>.bl_rna.properties`.
- Headless Blender with the user's normal add-ons enabled often hangs — always
  `--factory-startup` in scripts, and register only what the harness needs.
- **`publish_repo.sh` keeps prior version zips → the remote index serves
  overlapping-range duplicates (both have `blender_version_min=5.0.0`,
  `blender_version_max=null`) → Blender's resolver installs the FIRST listed,
  i.e. the OLDER version.** Symptom: "update from remote" pulls an old version
  even though a newer one is published. Fix used 2026-07-08: `rm` the stale zip
  from `~/.no3d-extension-repo/`, re-run `extension server-generate`, force-push
  `gh-pages`. The pipeline (`ship.sh`) must PRUNE old zips (or pin
  `blender_version_max`) so the repo serves exactly one current build per
  Blender-version band. This is a top-priority `ship.sh` requirement.
- **Merged add-on vs. still-installed standalone add-ons COLLIDE.** After
  merging Claude Pair + Save & Reload into the add-on, the standalone
  `claude_pair` and `save_and_reload` extensions were still enabled and
  register the SAME `bl_idname`s (`claude_pair.pair_now`, `save_and_reload.run`,
  the `CLAUDE_PAIR_PT_panel`, etc.). Blender does last-registered-wins, but
  running both is genuinely conflicting, and the standalone's now-dropped
  operators (`CLAUDE_PAIR_OT_reload`/`_uninstall`) linger on `bpy.types` as
  ghosts. Disabling a standalone LIVE (mid-session) after the merged copy
  re-registered over it throws `unregister_class(...): missing bl_rna attribute`
  (its classes were already yanked out from under it) — messy but non-fatal.
  **Migration rule:** disable/uninstall the standalones BEFORE (or instead of)
  enabling the merged add-on, then RESTART Blender to clear ghost registrations.
  Never rely on live disable to fully clean up. A future `ship.sh`/migration
  helper should detect and warn about enabled standalones.
- Disabling standalone Claude Pair mid-session tears down the MCP server it
  runs (the port that hosts the paired Claude session). Do it at a restart, not
  live, unless you intend to orphan the current session.
- `bpy.context.preferences.use_preferences_save` is often OFF here — enablement
  changes made via `addon_disable`/`addon_enable` do NOT persist across restart
  unless you explicitly `bpy.ops.wm.save_userpref()`. Always save after a
  migration you need to survive a restart.
