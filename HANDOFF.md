# HANDOFF — 2026-07-08 (before Blender + Claude restart)

Read this first if you're a fresh agent picking up the No3d Asset Developer work.
Also read `AGENTS.md` (guardrails + Lessons) and `.superpowers/sdd/progress.md`.

## Where things stand

### DONE and shipped
- **Merge complete + on `main` + pushed.** Claude Pair and Save & Reload are
  merged into the add-on as subpackages `claude_pair/` and `save_reload/`, at
  **v3.2.0**. `main` @ commit `8321546` (merge commit), pushed to
  `github.com/node-dojo/no3d-asset-developer`. Feature branch deleted.
- **Register gate + build gate both green.** `tools/check_register.sh` →
  `REGISTER_OK`; headless `extension build` produced
  `dist/no3d_asset_developer-3.2.0.zip`.
- **Published to the remote extension repo.** `tools/publish_repo.sh` pushed
  3.2.0 to `gh-pages`; after a duplicate-version fix (see below) the repo now
  serves **3.2.0 ONLY** at `node-dojo.github.io/no3d-asset-developer/index.json`.
- **Smoke test PASSED on the real remote-installed 3.2.0** in the paired Blender
  (pid 83584): add-on updated from the GitHub repo, enabled; all 15 folded prefs
  present with correct defaults; Claude Pair in its own "Claude" N-panel tab;
  Save & Reload in the File menu with Cmd+Shift+R; `pair_now` present.

### Two real bugs the smoke test surfaced (now documented in AGENTS.md Lessons)
1. **Remote repo served duplicate versions → Blender installed the OLDER one.**
   `publish_repo.sh` keeps prior zips; with overlapping version ranges Blender's
   resolver picks the first (older) listed. FIXED for now by pruning the stale
   3.1.0 zip and republishing. The pipeline `ship.sh` MUST prune old zips.
2. **Merged add-on collides with still-installed standalone add-ons.** Standalone
   `claude_pair` (v0.1.0) and `save_and_reload` register the same `bl_idname`s.
   Migration = disable/uninstall the standalones, then RESTART Blender.

### State persisted for the restart (already saved via `wm.save_userpref()`)
- `bl_ext.https.no3d_asset_developer` (merged 3.2.0) → **ENABLED**
- standalone `bl_ext.user_default.claude_pair` → **DISABLED**
- standalone `bl_ext.addons.save_and_reload` → **DISABLED**
- stale 3.0.0 copies (`bl_ext.addons.*`, `bl_ext.user_default.no3d_asset_developer`)
  → **DISABLED**

## Why you're restarting
Ghost operator registrations (`CLAUDE_PAIR_OT_reload`/`_uninstall`) from the
standalone Claude Pair's messy live-teardown linger on `bpy.types`. A Blender
restart loads ONLY the merged 3.2.0 (standalones now disabled + saved) and clears
the ghosts. This session's MCP link (port 9877, run by standalone Claude Pair)
drops on restart — expected; re-pair after.

## FIRST THING to verify in the new session (post-restart)
Confirm the clean end-state held:
- Merged 3.2.0 is the ONLY enabled feature owner; standalones stayed disabled.
- `hasattr(bpy.types, 'CLAUDE_PAIR_OT_reload')` is now **False** (ghosts gone).
- The "Claude" N-panel tab, File→Save and Reload, and the add-on prefs page's
  Save&Reload + Claude Pair boxes all render.

## NEXT planned work (not started)
Write + execute the **ship-pipeline implementation plan** from
`docs/superpowers/specs/2026-07-08-ship-pipeline-design.md`:
- `tools/ship.sh` (build → github → gumroad), **with a zip-prune step** (bug #1).
- Claude Pair "Ship" menu (agent vs quick-republish).
- Vault playbook + session logging + recursive learning loop.
- **Fold bug #1 (prune) and bug #2 (standalone-collision migration) into the
  pipeline as first-class requirements** — they are the two hardest-won lessons
  from this session.
Gumroad product for the add-on: **"No3d Asset Developer"**, id
`MF2z7ZAjY-W9p4b_KOLjvw==`.

## Key paths
- Canonical repo (edit here): `/Users/joebowers/Projects/no3d-asset-developer`
  → remote `github.com/node-dojo/no3d-asset-developer` (main + gh-pages).
- STALE copy (do NOT edit): `<The Well Code>/solvet-global/no3d-asset-developer/`
  (has a `STALE_DO_NOT_EDIT.md` breadcrumb).
- Scratch publish repo: `~/.no3d-extension-repo/` (gitignored, outside Dropbox).
- Specs: `docs/superpowers/specs/`  Plans: `docs/superpowers/plans/`
  SDD ledger/reports: `.superpowers/sdd/`
