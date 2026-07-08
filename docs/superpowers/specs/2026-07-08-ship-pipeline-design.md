# No3d Asset Developer — "Ship a Feature" pipeline

**Date:** 2026-07-08
**Target repo:** `/Users/joebowers/Projects/no3d-asset-developer` → `github.com/node-dojo/no3d-asset-developer`
**Relationship to the merge spec:** The Claude-Pair + Save-&-Reload merge
(`2026-07-08-merge-claude-pair-save-reload-design.md`) is the **first worked example** of this
pipeline. Build the merge, then ship it through this pipeline to prove the loop end-to-end.

## Problem

Transferring new add-on features from Joe's home Mac to his work Mac happens by updating the
No3d Asset Developer add-on and letting the work Blender pull it as a remote extension repo.
Today the distribution backbone works but the *front half* is manual and un-documented, so
every feature-integration session re-teaches an agent the same steps. Joe wants:
idea → integration → build → **GitHub + Gumroad** → auto-pull into work Blender, as a
**frictionless, recurring** flow, documented once, with **session logging** and a
**recursive learning loop** so agents stop needing repeat instruction.

## What already exists (do NOT rebuild)

- `repo_registration.py` — work Blender self-subscribes to
  `node-dojo.github.io/no3d-asset-developer/index.json` and pulls updates natively. **The
  auto-pull-to-work-Blender leg is done.**
- `tools/publish_repo.sh` — headless `extension build` → `extension server-generate` →
  force-push `gh-pages`. **The GitHub-Pages distribution leg is done.**
- `gumroad` CLI at `~/.local/bin/gumroad`, authed. Gumroad product **"No3d Asset Developer"**
  exists, published, id `MF2z7ZAjY-W9p4b_KOLjvw==`.

### Adjacent-but-different (name-collision hazard — document, don't touch)

- `<The Well Code>/no3d-remote-publish/` (`publish.py`) publishes the **WIP asset *library***
  (blend assets) to **Supabase Storage**. That is a *different* pipeline from shipping the
  *add-on code*. The pipeline doc must call out the distinction so agents don't conflate them.

## Architecture: deterministic spine + agent-driven front

**Confirmed split:** a deterministic script owns build/publish; the agent owns the judgment
(merge the feature, pick the version, write release notes).

```
tools/ship.sh  — the mechanical spine (build + publish + log)
Claude Pair    — the human/agent front (menu button + baked instructions)
Vault docs     — the knowledge layer (pipeline playbook + session log + lessons)
```

### `tools/ship.sh`

```
tools/ship.sh [--version X.Y.Z] [--no-gumroad] [--dry-run] [--notes "..."]

  1. Preflight — working tree clean, on main, manifest version == bl_info version.
                 Abort with a clear message otherwise.
  2. Bump      — if --version given, set it in BOTH blender_manifest.toml and
                 __init__.py bl_info (each a one-line edit). Re-verify they match.
  3. Build     — "$BLENDER" --factory-startup --command extension build
                 --source-dir . --output-filepath dist/no3d_asset_developer-X.Y.Z.zip
  4. GitHub    — git commit (version bump + any staged feature work must already be
                 committed by the agent; ship.sh commits only the version bump if needed),
                 git tag vX.Y.Z, git push origin main --tags,
                 then run tools/publish_repo.sh (gh-pages index refresh).
  5. Gumroad   — unless --no-gumroad:
                 gumroad products update MF2z7ZAjY-W9p4b_KOLjvw== \
                   --replace-files --file dist/no3d_asset_developer-X.Y.Z.zip
                 (--replace-files swaps the whole file set for the new zip — verified.)
  6. Log       — append a structured entry (facts) to the vault ship-log (see Logging).
                 Print a summary block: version, tag, gh-pages URL, Gumroad product URL.
```

`--dry-run` prints the plan for stages 3–5 without building/pushing/uploading. `BLENDER`
path is a variable at the top (currently `/Applications/Blender 5.2 Beta.app`), matching
`publish_repo.sh`.

**ship.sh does the mechanical half only.** It does NOT merge features or decide versions —
the agent does that first, commits the feature, then invokes ship.sh.

### Claude Pair front: a two-item menu

Add to Claude Pair's N-panel (its own "Claude" tab — this rides on top of the merge that
brings Claude Pair into the add-on) a **"Ship No3d Dev"** button that opens a small menu:

- **"Ship (agent)"** — drops a `SHIP_REQUEST.md` marker in the pair's cwd (with an optional
  notes field) and reveals the terminal. The paired agent reads the marker, does the
  judgment half (confirm the feature is merged + committed, pick the version bump, write
  release notes), then runs `tools/ship.sh --version … --notes …`. Agent stays in the loop.
- **"Quick republish (script only)"** — fires `tools/ship.sh` directly (no version bump,
  no agent) for a pure re-publish of the current committed state. For the case where code
  is already shipped-ready and you just want the zip regenerated + pushed.

The menu is a new operator (`claude_pair.ship_menu`) living in the merged `claude_pair/`
subpackage. "Quick republish" runs ship.sh via the same detached-subprocess pattern
Save & Reload uses; "Ship (agent)" only writes the marker + reveals — it never blocks Blender.

### Baked instructions (single source of truth)

- **Canonical playbook:** `$VAULT_001/Agent/Reference/no3d-asset-developer-pipeline.md`.
  Contains: the numbered idea→publish steps, the `ship.sh` contract, the Gumroad product id,
  the gh-pages URL, the WIP-library-vs-add-on distinction, and a living **"Lessons / gotchas"**
  section (see Learning Loop).
- **Claude Pair pointer:** add ONE line to `~/.claude-pair/global-context.md` pointing at the
  playbook, so every paired session's system prompt references it. (That file stays short by
  design — one pointer line, not the content.)
- **Repo pointer:** a short `PIPELINE.md` at the repo root that points at the vault playbook,
  so the flow is discoverable from GitHub too. Vault remains the single source of truth.

## Session logging

Per Joe's vault-as-record convention, logs live in the vault, not the repo.

- **Ship log:** `$VAULT_001/PROJECTS/no3d tools/ship-log.md` — one dated entry per ship.
  `ship.sh` stage 6 appends the **mechanical facts** (version, tag, git SHA, gh-pages URL,
  Gumroad URL, timestamp). The agent appends the **narrative** (what the feature was, why).
- **Session log:** the playbook instructs every paired agent to open/append a session log at
  session start (under the same `no3d tools` card) and close it at ship — so sessions that
  don't end in a ship still leave a record. Absolute dates only (per global CLAUDE.md).

## Recursive learning loop

The anti-repetition mechanism. All state lives in the **one playbook doc every agent reads**.

1. **Read** — the playbook's standing first instruction: "read the Lessons / gotchas section
   before running the pipeline."
2. **Run** — execute the pipeline.
3. **Correct** — when Joe corrects the agent, or the agent hits a gotcha, it writes the lesson
   as a bullet under Lessons / gotchas in the playbook (not a scattered note).
4. **Promote** — periodically (human-triggered, to avoid bloat) durable rules graduate from
   Lessons into the numbered procedure steps, becoming procedure instead of folklore.

Loop: read lessons → run → correct → write lesson → (occasionally) promote. Because it lives
in the doc Claude Pair points every agent to, a correction given once becomes the next agent's
starting instruction.

## Constraints & notes

- **macOS only** (Blender.app paths, `open`, iTerm2) — consistent with the rest of Joe's setup.
- **Gumroad two-step reality:** `gumroad files upload` puts a file in the attachments
  namespace; **attaching to the product** is `gumroad products update <id> --replace-files
  --file <zip>`. The pipeline uses the single `products update` form (verified to accept a
  local `--file`), so no separate upload/attach dance is needed.
- **Version discipline:** the version string is duplicated in `blender_manifest.toml` and
  `__init__.py` bl_info. ship.sh's preflight refuses to proceed if they disagree; the bump
  stage edits both. (Candidate first Lesson: "always bump both.")
- **Secrets:** Gumroad auth is already in the CLI's stored token; no secrets in the repo.
  If any stage needs Doppler-scoped creds later, inject via `doppler run --` (never on disk).
- **gh-pages force-push** is inherited from `publish_repo.sh` (it owns a scratch repo outside
  Dropbox). ship.sh calls it rather than reimplementing it.

## Verification

1. `tools/ship.sh --dry-run` prints a correct plan without side effects.
2. A real ship of the merge feature produces: a new `dist/*.zip`, a pushed `vX.Y.Z` tag, a
   refreshed gh-pages index, the Gumroad product's file replaced, and a new ship-log entry.
3. On the **work Mac**, Blender's Get Extensions shows the new version available and installs
   it (the auto-pull leg, already working — this confirms the full loop).
4. The Claude Pair menu appears and both items behave (marker+reveal vs. direct script).

## Out of scope

- No change to the WIP-library Supabase publisher (`no3d-remote-publish`).
- No CI/GitHub Actions runner — shipping is initiated from Joe's home Mac (has Blender + the
  repo). A hosted runner could come later but isn't needed for the stated goal.
- No multi-product / variant Gumroad handling — one product, replace its file.
- No Windows/Linux support.
