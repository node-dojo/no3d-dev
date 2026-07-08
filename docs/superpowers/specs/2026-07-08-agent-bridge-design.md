# Agent Bridge — Design

**Date:** 2026-07-08
**Status:** Design — pending user review
**Project card:** `$VAULT_001/PROJECTS/Agent Bridge/Agent Bridge.md`
**Repo:** `no3d-asset-developer` (sibling to the `claude_pair/` subpackage)

---

## 1. Goal

Let any number of Claude Code agents, launched from anywhere on the system, connect to any number of open Blender instances, addressing each instance by its open `.blend` filename, with instances registering and dropping out automatically as they open and close — so connections never collide, never require stopping another instance's server, and never go stale when Blender restarts.

**One line:** Replace the single, fought-over Blender MCP port with a resolver that routes an agent's calls to the live Blender named by its `.blend` file — sticky per session, switchable mid-conversation by the agent on the user's request.

## 2. Problem (root cause)

The Blender MCP ecosystem addresses Blender by a **port number**, default `localhost:9876`:

- `blmcp` (the official MCP server the user runs) reads `BLENDER_MCP_PORT` in `tools_helpers/connection.py:get_connection_params()`, freshly on **every** tool call, and opens a new socket per call.
- The **listener lives inside Blender** (the add-on's socket server). Only one process can `bind()` a given port, so the first Blender to start its server **hogs** the well-known `9876`. Handing it to another instance means stopping the hog's server first.
- Ports also go **stale**: an agent bound to a port at launch breaks when that Blender restarts on a different free port → connection-refused errors.

The port is the wrong naming layer. The user thinks in terms of *which `.blend`*, not *which port*. (This is a CLAUDE.md rule-3 violation baked into the upstream protocol: the address is a raw number, typed/frozen per process, not a stable name resolved from one source of truth.)

## 3. Connection model — Sticky + agent-switchable (DECIDED)

An agent has **one active target Blender at a time**:

- Resolved once when first needed (or set explicitly), then **sticky** — every subsequent tool call goes to that same Blender.
- The agent can **switch** the active target mid-conversation by calling a new tool, `use_instance("foo.blend")`, when the user asks in chat ("switch to the asset-dev file").
- This is **not** per-call targeting. There is exactly one active target at any instant.

### Why sticky, not per-call

Per-call was evaluated and rejected. Trade-offs, all cutting the same way:

| Concern | Sticky (chosen) | Per-call (rejected) |
|---|---|---|
| Wrong-target blast radius | Contained to the one active target | Any call can hit the wrong file (agent fumbles target arg → destructive op on wrong Blender) |
| Confirmable "current target" | Yes — single, displayable answer | No stable "current" instance to confirm/audit |
| Agent's mental model | One coherent world | Must thread target through every call; scene-state assumptions go stale |
| Failure semantics | Clean (one Blender dies → obviously broken) | Partial (subset of calls fail) |
| Build/maintenance | Swap one resolver function | Shim over the entire tool surface |
| "One agent spans 2 Blenders in one step" | Sequential (A→B→A) | Interleaved — but see note |

**Note on the per-call "superpower":** because each call is an independent socket that closes after (`send_code()`), nothing persists in the connection between calls. So even per-call must do *read-A-fully → act-on-B*; it cannot hold Blender-A state "open" while calling B. The headline benefit is therefore thin, and sticky's A→B→A switch achieves the realistic workflow ("copy the bracket from resin into asset-dev") in two beats.

## 4. Build shape — extend `blmcp` at one seam, do NOT fork

Agent Bridge **is `blmcp` with a smarter address book**, delivered as a thin adapter that depends on unmodified upstream `blmcp` as a library.

### The seam

`blmcp` funnels every tool through `send_code()` → `get_connection_params()` (both in `tools_helpers/connection.py`). Tools are auto-discovered by `blmcp/__init__.py:main()` via `pkgutil.iter_modules`. So:

- Replace **one function's behavior** (`get_connection_params`, and/or `send_code`) with a registry-backed resolver.
- Add **one tool** (`use_instance`) to the same `mcp` object.
- Call upstream `main()`. All ~30 tools are inherited and auto-registered as normal.

### Coupling strategy — pin + monkeypatch + smoke test (DECIDED; overridable)

- **Do not vendor/fork** `blmcp` source. Depend on a **pinned** upstream. Note: the package is distributed as `blender-mcp==1.0.0` installed **from git** (`projects.blender.org/lab/blender_mcp`, subdirectory `mcp`), not a PyPI semver — so the pin is a **git ref/commit**, recorded in Agent Bridge's dependency spec.
- **Monkeypatch exactly one function:** `blmcp.tools_helpers.connection.get_connection_params`. This is the correct seam because **17 of the tools do `from blmcp.tools_helpers.connection import send_code` (name-bound at import)** — patching `send_code` after import would NOT affect them. But `send_code` calls `get_connection_params()` **unqualified within its own module** (`connection.py:44`), resolved at call time, so replacing `connection.get_connection_params` lands for every tool. Agent Bridge is ~50 lines of its own code, not a copy of theirs.
- Ship a **smoke test** that asserts `get_connection_params` still exists with the expected 0-arg → `(host, port)` signature, and that `send_code` still resolves it unqualified (i.e. our patch still lands), so an upstream rename/refactor fails **loudly** at test time, not silently at runtime.
- Upgrade the git pin **deliberately**, on our schedule; new tools + protocol fixes come for free when we bump it.

Rejected alternatives:
- **Wrap-the-server (W1):** re-declare 30 tool schemas + babysit a child process. Brittle, breaks on any tool-set change.
- **Hard fork:** manual re-sync every upstream release (they ship ~biweekly). The treadmill this project exists to kill.
- **Track-latest + silent fallback:** a graceful fallback to env-var behavior could mask a broken router — targeting silently stops working. Rejected in favor of failing loud.

## 5. Architecture — two halves

```
┌─────────────────────────┐         ┌──────────────────────────────┐
│ Blender instance A      │         │ Agent Bridge (MCP server)    │
│  no3d asset dev.blend   │         │  = blmcp + patched resolver  │
│  add-on socket :9877 ───┼──┐      │  + use_instance tool         │
│  registers self ────────┼─┐│      │                              │
└─────────────────────────┘ ││      │  active_target (in memory)   │
┌─────────────────────────┐ ││      │  = "no3d asset dev"          │
│ Blender instance B      │ │└─────►│                              │
│  resin tests.blend      │ │  reads│  per call:                   │
│  add-on socket :9878 ───┼─┼──────►│   filename → live port       │
│  registers self ────────┼─┘ registry (via registry.py)          │
└─────────────────────────┘         └───────────┬──────────────────┘
                                                 │ send_code() to resolved port
                    ~/.blender-pairs/<pid>.json ◄┘
```

### Half A — Blender-side registration (extends existing Claude Pair registry)

Each Blender that starts its MCP server writes/refreshes a registry entry so Bridge can find it by filename. **Reuses the Claude Pair registry** (`~/.blender-pairs/<pid>.json`, `registry.py`, `gc_dead()`), adding the fields Bridge needs:

Registry entry (superset of today's):
```json
{
  "blender_pid": 25591,
  "port": 9877,
  "host": "localhost",
  "blendfile": "/…/no3d asset dev work.001.blend",
  "blendfile_stem": "no3d asset dev work.001",
  "started_at": 1720000000.0
}
```
- `blendfile_stem` is the address key agents use.
- Registration happens wherever the Blender-side server starts (Claude Pair's pair flow already writes this; Agent Bridge's Blender-side piece ensures a plain "serve" also registers, independent of pairing).
- **Liveness:** Bridge calls `gc_dead()` (already exists — `os.kill(pid, 0)`) before resolving, so dead instances never resolve.

### Half B — Agent-side MCP (the Bridge server)

- Entry point `agent-bridge` (new console script), registered as the `blender` MCP server in Claude Code config in place of `blender-mcp`.
- At startup: `import blmcp`, monkeypatch the resolver, register `use_instance`, run `blmcp.main()`.
- Holds `active_target: str | None` in subprocess memory.
- **Mirrors** the active target to the registry keyed by the agent's own identity (see §7) so the Blender panel + Copy Diagnostics can display "agent → targeting X".

## 6. Resolver behavior (the core logic)

On each `send_code()` (i.e. each tool call):

1. If `active_target is None`: resolve a default (see below) and set it sticky.
2. `gc_dead()`, then look up live registry entries whose `blendfile_stem` matches `active_target`.
3. **0 matches** → raise a clear `ConnectionError`: *"No live Blender editing '<target>'. Open it, or use_instance() to pick another. Live instances: [list]."*
4. **1 match** → use its `host:port`. Proceed exactly as upstream `send_code()`.
5. **>1 match (same `.blend` open twice)** → **refuse**, list the PIDs, instruct the agent to disambiguate: `use_instance("<target>", pid=NNNN)`. (No silent wrong-target. — DECIDED)

**Default target when none set** (first call, agent never called `use_instance`):
- If exactly **one** live Blender is registered → use it (the common case; zero friction).
- If **zero** → error as in step 3.
- If **>1** → refuse and list them; require an explicit `use_instance(...)`. (Safe: never guess among several.)

## 7. New tool — `use_instance`

```
use_instance(target: str, pid: int | None = None) -> str
```
- Sets the sticky `active_target` for this agent session.
- `target`: `.blend` filename stem (case-insensitive, extension optional).
- `pid`: optional tiebreaker when the same file is open in multiple instances.
- Returns a confirmation string: resolved file, PID, port — so the agent can state "Now targeting `assetdev` (pid 25591, :9877)" to the user.
- Also exposes a read path — a companion tool or the return of `use_instance()` with no change — so the agent can **list live instances** ("what Blenders can I connect to?"). Design: a second tiny tool `list_instances() -> [{stem, pid, port, blendfile}]`.

**Active-target storage:** in-memory in the Bridge subprocess (source of truth), mirrored to `~/.blender-pairs/agents/<agent-port>.json` (or similar) for observability. Mirror write is best-effort; a failed mirror never blocks a call.

## 8. Relationship to Claude Pair

- **Separate add-on / separate concern.** Claude Pair = "spawn a paired terminal + session lifecycle for ONE Blender." Agent Bridge = "route any agent's calls to any live Blender by name."
- **Shared registry** is the integration point. Bridge reads what Pair (and the Blender-side serve action) writes. No code coupling beyond the registry module, which can be shared/vendored.
- Claude Pair's original two requested features (click-to-copy PID/port; open-a-port button) are **superseded**: with Bridge, agents address by filename, so copying ports is no longer the workflow. The Blender-side "serve + register" action replaces "open a port."

## 9. Components & boundaries (black boxes)

| Unit | Responsibility | Depends on | Interface |
|---|---|---|---|
| `registry` (shared) | Persist/read/gc live Blender entries | filesystem | `read/write/remove/list_all/gc_dead` |
| Blender-side serve+register | Start add-on socket server, write registry entry with `blendfile_stem` | `registry`, official MCP add-on | Blender operator / panel button |
| `resolver` (Bridge) | filename → live host:port; sticky state; ambiguity rules | `registry` | patched `get_connection_params`/`send_code` |
| `use_instance` / `list_instances` tools | Agent-facing target control + discovery | `resolver`, `registry` | MCP tools |
| Bridge entry point | import blmcp, patch, register tools, run | `blmcp`, above | `agent-bridge` console script |
| smoke test | assert upstream seams intact | `blmcp` | CI/dev check |

## 10. Error handling

- **No live target / stale target:** clear `ConnectionError` naming the target and listing live alternatives (reuses upstream's ConnectionError contract so agent fallback logic still works).
- **Ambiguous target:** refuse + list PIDs; never guess.
- **Upstream seam moved:** smoke test fails loudly; runtime patch raises at startup rather than silently falling back.
- **Registry corruption/partial write:** `registry.read` already swallows `JSONDecodeError`; treat unreadable entries as absent.
- **Mirror write failure:** logged, non-fatal.

## 11. Testing strategy

- **Unit (resolver):** table-driven over registry states — 0/1/N live matches, stale PID present, extension/case variations, pid tiebreak. No Blender needed (registry is just JSON on disk).
- **Smoke (coupling):** assert `blmcp.tools_helpers.connection.get_connection_params` exists (0-arg → `(host, port)`), that `send_code` exists, and that patching `get_connection_params` is observed by a `send_code` call (patch-lands check) against the pinned git ref.
- **Integration (manual/scripted):** two Blenders open on distinct ports; one agent; `list_instances` → `use_instance(A)` → call → `use_instance(B)` → call; verify each call hit the right instance (assert via a marker object created per-instance).
- **Regression:** with a single Blender and no `use_instance` call, behavior matches plain `blmcp` (default-target path).

## 12. Out of scope (v1)

- Full per-call targeting (one agent interleaving Blenders within a single step).
- Load balancing / pooling across Blenders.
- Remote (non-localhost) Blenders.
- Auto-launching Blender instances on demand.
- Windows/Linux specifics (macOS-first, matching Claude Pair).

## 13. Open items to confirm at review

- Console-script name: `agent-bridge` (ok?).
- Whether the Blender-side "serve + register" lives as a new operator in Agent Bridge's own Blender-side module, or is folded into Claude Pair's existing serve path.
- Exact mirror-file location for agent→target observability.
