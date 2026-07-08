# Agent Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a thin MCP server (`agent-bridge`) that routes an agent's Blender tool calls to the live Blender instance named by its `.blend` filename — sticky per session, switchable mid-conversation via a `use_instance` tool.

**Architecture:** Agent Bridge depends on unmodified upstream `blmcp` as a library. At startup it monkeypatches one function — `blmcp.tools_helpers.connection.get_connection_params` — with a registry-backed resolver, registers two new tools (`use_instance`, `list_instances`), and runs `blmcp.main()`. All ~30 upstream tools are inherited and auto-registered unchanged. A Blender-side operator makes each Blender register its live socket + `.blend` stem into the shared `~/.blender-pairs/` registry so the resolver can find it.

**Tech Stack:** Python 3.12, `bpy` (Blender add-on side), upstream `blmcp` (`blender-mcp` from git), `pytest`.

## Global Constraints

- **Do NOT fork/vendor `blmcp`.** Depend on it as a library, pinned to a git ref. Package is `blender-mcp` installed from `https://projects.blender.org/lab/blender_mcp.git` subdirectory `mcp` (currently `1.0.0`).
- **Patch exactly one seam:** `blmcp.tools_helpers.connection.get_connection_params`. Never patch `send_code` (17 tools name-bind it at import; the patch would not land). `send_code` calls `get_connection_params()` unqualified at call time (`connection.py:44`), so patching that function lands for all tools.
- **Reuse the existing registry** at `~/.blender-pairs/<pid>.json` (`claude_pair/registry.py`). Do not invent a second registry format.
- **Address key is the `.blend` filename stem** (case-insensitive, extension optional).
- **Ambiguity (same file open twice) → refuse and list PIDs.** Never silently guess.
- **Default target when none set:** exactly-one-live → use it; zero → error; >1 → refuse and list. Never guess among several.
- **macOS-first** (matches Claude Pair). No Windows/Linux-specific work in v1.
- **Console-script name:** `agent-bridge` (default; confirm at first task).
- Every file starts with `# SPDX-License-Identifier: GPL-3.0-or-later` to match the repo.
- Frequent commits: one per task minimum.

---

## File Structure

New subpackage `agent_bridge/` in the repo root (sibling to `claude_pair/`):

| File | Responsibility |
|---|---|
| `agent_bridge/__init__.py` | Blender add-on side: `register()`/`unregister()`, the serve+register operator, panel button. |
| `agent_bridge/resolver.py` | Pure resolver: given registry state + sticky target, return `(host, port)` or raise. No `blmcp`, no `bpy`. |
| `agent_bridge/bridge_server.py` | Agent-side MCP entry point: monkeypatch, register `use_instance`/`list_instances`, run `blmcp.main()`. |
| `agent_bridge/registry.py` | Thin re-export/extension of `claude_pair.registry` (shared format) with the `blendfile_stem` helper. |
| `tests/agent_bridge/test_resolver.py` | Unit tests for resolver (table-driven, no Blender). |
| `tests/agent_bridge/test_coupling_smoke.py` | Smoke test: upstream seam intact + patch lands. |
| `pyproject.toml` (or equivalent) | Declares the `agent-bridge` console script + pinned `blender-mcp` git dep. |

Resolver is deliberately `bpy`-free and `blmcp`-free so it is unit-testable against plain JSON on disk.

---

### Task 1: Shared registry helper (`blendfile_stem`)

**Files:**
- Create: `agent_bridge/registry.py`
- Test: `tests/agent_bridge/test_resolver.py` (created here, reused Task 2)

**Interfaces:**
- Consumes: `claude_pair/registry.py` (`REGISTRY_DIR`, `read`, `write`, `remove`, `list_all`, `gc_dead`).
- Produces:
  - `live_instances() -> list[dict]` — `gc_dead()` first, then `list_all()`; each dict has at least `blender_pid`, `port`, `host`, `blendfile`, `blendfile_stem`.
  - `stem_of(entry: dict) -> str` — returns `entry["blendfile_stem"]` if present, else derives from `entry["blendfile"]` (Path.stem), else `""`.

- [ ] **Step 1: Write the failing test**

```python
# tests/agent_bridge/test_resolver.py
from agent_bridge import registry as reg

def test_stem_of_prefers_explicit_field():
    assert reg.stem_of({"blendfile_stem": "resin", "blendfile": "/x/other.blend"}) == "resin"

def test_stem_of_derives_from_blendfile_when_no_stem():
    assert reg.stem_of({"blendfile": "/a/b/no3d asset dev.blend"}) == "no3d asset dev"

def test_stem_of_empty_when_nothing():
    assert reg.stem_of({}) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/agent_bridge/test_resolver.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_bridge'` (or `AttributeError: stem_of`).

- [ ] **Step 3: Write minimal implementation**

```python
# agent_bridge/registry.py
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared pair-registry access for Agent Bridge (reuses claude_pair's format)."""

from pathlib import Path

from claude_pair import registry as _base

REGISTRY_DIR = _base.REGISTRY_DIR
read = _base.read
write = _base.write
remove = _base.remove
list_all = _base.list_all
gc_dead = _base.gc_dead


def stem_of(entry: dict) -> str:
    stem = entry.get("blendfile_stem")
    if stem:
        return str(stem)
    bf = entry.get("blendfile")
    if bf:
        return Path(bf).stem
    return ""


def live_instances() -> list[dict]:
    gc_dead()
    return list_all()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/agent_bridge/test_resolver.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add agent_bridge/registry.py tests/agent_bridge/test_resolver.py
git commit -m "feat(agent-bridge): shared registry helper with blendfile_stem"
```

---

### Task 2: Resolver core (sticky target + ambiguity rules)

This is the heart of Agent Bridge. Pure function over registry state; no `bpy`, no `blmcp`.

**Files:**
- Create: `agent_bridge/resolver.py`
- Test: `tests/agent_bridge/test_resolver.py` (append)

**Interfaces:**
- Consumes: `agent_bridge.registry.live_instances()`, `stem_of()`.
- Produces:
  - `class TargetError(Exception)` — raised for no-match / ambiguous / no-default, message lists live instances.
  - `class Resolver` with:
    - `__init__(self, instances_fn=registry.live_instances)` — injectable for tests.
    - `active_target: str | None` and `active_pid: int | None` attributes (sticky state).
    - `set_target(self, target: str, pid: int | None = None) -> dict` — resolve + store sticky; returns the chosen entry; raises `TargetError` on 0/ambiguous.
    - `resolve(self) -> tuple[str, int]` — returns `(host, port)` for the current sticky target; if none set, applies the default rule; raises `TargetError` otherwise.
    - `list_live(self) -> list[dict]` — pass-through of live instances (for `list_instances` tool).
  - `_match(instances, target, pid) -> list[dict]` — case-insensitive stem match, optional `.blend` suffix stripped from `target`, optional pid filter.

- [ ] **Step 1: Write the failing tests**

```python
# tests/agent_bridge/test_resolver.py  (append)
import pytest
from agent_bridge import resolver as R

def _inst(pid, port, stem, host="localhost"):
    return {"blender_pid": pid, "port": port, "host": host,
            "blendfile": f"/x/{stem}.blend", "blendfile_stem": stem}

def make(instances):
    return R.Resolver(instances_fn=lambda: list(instances))

def test_set_target_single_match():
    r = make([_inst(1, 9877, "resin"), _inst(2, 9878, "assetdev")])
    entry = r.set_target("resin")
    assert entry["port"] == 9877
    assert r.resolve() == ("localhost", 9877)

def test_target_match_is_case_insensitive_and_ext_optional():
    r = make([_inst(1, 9877, "Resin")])
    r.set_target("resin.blend")
    assert r.resolve() == ("localhost", 9877)

def test_no_match_raises_listing_live():
    r = make([_inst(1, 9877, "resin")])
    with pytest.raises(R.TargetError) as ex:
        r.set_target("nope")
    assert "resin" in str(ex.value)

def test_ambiguous_same_file_twice_refuses_and_lists_pids():
    r = make([_inst(1, 9877, "resin"), _inst(2, 9879, "resin")])
    with pytest.raises(R.TargetError) as ex:
        r.set_target("resin")
    assert "1" in str(ex.value) and "2" in str(ex.value)

def test_ambiguous_resolved_by_pid():
    r = make([_inst(1, 9877, "resin"), _inst(2, 9879, "resin")])
    entry = r.set_target("resin", pid=2)
    assert entry["port"] == 9879

def test_default_single_live_used_when_no_target():
    r = make([_inst(7, 9880, "only")])
    assert r.resolve() == ("localhost", 9880)

def test_default_zero_live_raises():
    r = make([])
    with pytest.raises(R.TargetError):
        r.resolve()

def test_default_multi_live_refuses():
    r = make([_inst(1, 9877, "a"), _inst(2, 9878, "b")])
    with pytest.raises(R.TargetError) as ex:
        r.resolve()
    assert "a" in str(ex.value) and "b" in str(ex.value)

def test_sticky_survives_between_calls():
    r = make([_inst(1, 9877, "resin"), _inst(2, 9878, "assetdev")])
    r.set_target("assetdev")
    assert r.resolve() == ("localhost", 9878)
    assert r.resolve() == ("localhost", 9878)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agent_bridge/test_resolver.py -v`
Expected: FAIL — `AttributeError: module 'agent_bridge.resolver' has no attribute 'Resolver'`.

- [ ] **Step 3: Write minimal implementation**

```python
# agent_bridge/resolver.py
# SPDX-License-Identifier: GPL-3.0-or-later
"""Registry-backed resolver: sticky .blend target -> live (host, port)."""

from . import registry


class TargetError(Exception):
    """No live match, ambiguous match, or no safe default."""


def _norm(name: str) -> str:
    name = name.strip().lower()
    if name.endswith(".blend"):
        name = name[: -len(".blend")]
    return name


def _describe(instances) -> str:
    if not instances:
        return "(no live Blender instances)"
    return ", ".join(
        f"{registry.stem_of(i)} (pid {i.get('blender_pid')}, :{i.get('port')})"
        for i in instances
    )


def _match(instances, target, pid):
    t = _norm(target)
    out = [i for i in instances if _norm(registry.stem_of(i)) == t]
    if pid is not None:
        out = [i for i in out if i.get("blender_pid") == pid]
    return out


class Resolver:
    def __init__(self, instances_fn=registry.live_instances):
        self._instances_fn = instances_fn
        self.active_target: str | None = None
        self.active_pid: int | None = None

    def list_live(self):
        return self._instances_fn()

    def set_target(self, target: str, pid: int | None = None) -> dict:
        instances = self._instances_fn()
        matches = _match(instances, target, pid)
        if not matches:
            raise TargetError(
                f"No live Blender editing '{target}'. "
                f"Live instances: {_describe(instances)}."
            )
        if len(matches) > 1:
            raise TargetError(
                f"'{target}' is open in multiple Blenders: {_describe(matches)}. "
                f"Disambiguate with use_instance(target, pid=...)."
            )
        self.active_target = registry.stem_of(matches[0])
        self.active_pid = matches[0].get("blender_pid")
        return matches[0]

    def resolve(self) -> tuple[str, int]:
        instances = self._instances_fn()
        if self.active_target is None:
            # Default rule.
            if len(instances) == 1:
                e = instances[0]
                return e.get("host", "localhost"), int(e["port"])
            if not instances:
                raise TargetError(
                    "No live Blender instances. Open a .blend and start its "
                    "Agent Bridge server, then use_instance()."
                )
            raise TargetError(
                f"Multiple Blenders live and no target set: {_describe(instances)}. "
                f"Pick one with use_instance(target)."
            )
        matches = _match(instances, self.active_target, self.active_pid)
        if not matches:
            raise TargetError(
                f"Target '{self.active_target}' is no longer live "
                f"(did that Blender close?). Live: {_describe(instances)}."
            )
        if len(matches) > 1:
            raise TargetError(
                f"Target '{self.active_target}' now matches multiple Blenders: "
                f"{_describe(matches)}. Re-pick with use_instance(target, pid=...)."
            )
        e = matches[0]
        return e.get("host", "localhost"), int(e["port"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agent_bridge/test_resolver.py -v`
Expected: PASS (all resolver tests + Task 1 tests).

- [ ] **Step 5: Commit**

```bash
git add agent_bridge/resolver.py tests/agent_bridge/test_resolver.py
git commit -m "feat(agent-bridge): sticky resolver with ambiguity + default rules"
```

---

### Task 3: Monkeypatch + entry point (`bridge_server.py`)

**Files:**
- Create: `agent_bridge/bridge_server.py`
- Test: covered by Task 6 smoke test (this task's deliverable is verified there + by a manual run).

**Interfaces:**
- Consumes: `agent_bridge.resolver.Resolver`, upstream `blmcp`.
- Produces:
  - Module-level `RESOLVER = Resolver()` — the single sticky state for this subprocess.
  - `patched_get_connection_params() -> tuple[str, int]` — calls `RESOLVER.resolve()`, translating `TargetError` into `blmcp`'s `ConnectionError` so upstream fallback logic still works.
  - `install_patch() -> None` — sets `blmcp.tools_helpers.connection.get_connection_params = patched_get_connection_params`.
  - `main() -> int` — `install_patch()`, register bridge tools (Task 4), then `blmcp.main()`.

- [ ] **Step 1: Write the implementation**

```python
# agent_bridge/bridge_server.py
# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent Bridge MCP server: blmcp with a registry-backed connection resolver."""

from .resolver import Resolver, TargetError

RESOLVER = Resolver()


def patched_get_connection_params():
    """Replacement for blmcp's get_connection_params: route to the sticky target.

    blmcp's send_code() calls get_connection_params() unqualified at call time,
    so replacing the module attribute lands for every tool (including the 17
    that import send_code by name).
    """
    try:
        return RESOLVER.resolve()
    except TargetError as ex:
        # Translate to blmcp's error type so its ConnectionError-based fallbacks
        # and messages behave. send_code raises ConnectionError on socket issues;
        # a missing target is the same class of "cannot reach Blender" problem.
        raise ConnectionError(str(ex)) from ex


def install_patch() -> None:
    from blmcp.tools_helpers import connection
    connection.get_connection_params = patched_get_connection_params


def main() -> int:
    install_patch()
    # Register bridge-specific tools onto blmcp's mcp before it runs.
    from . import bridge_tools
    bridge_tools.install(RESOLVER)
    import blmcp
    return blmcp.main()
```

Note: `bridge_tools.install` is created in Task 4. Until then, `main()` will fail to import `bridge_tools` — that is expected and resolved in Task 4. This task commits the patch machinery only.

- [ ] **Step 2: Verify the patch lands in isolation**

Run:
```bash
python -c "
import agent_bridge.bridge_server as b
b.install_patch()
from blmcp.tools_helpers import connection
assert connection.get_connection_params is b.patched_get_connection_params, 'patch did not land'
# send_code must reach our patched func (no Blender needed: expect ConnectionError text from resolver)
try:
    connection.send_code('x', strict_json=False)
except ConnectionError as e:
    assert 'Blender' in str(e), repr(e)
    print('OK: send_code routed through patched resolver')
"
```
Expected: `OK: send_code routed through patched resolver` (resolver has no live instances → TargetError → ConnectionError).

- [ ] **Step 3: Commit**

```bash
git add agent_bridge/bridge_server.py
git commit -m "feat(agent-bridge): monkeypatch get_connection_params seam + entry point"
```

---

### Task 4: Bridge tools (`use_instance`, `list_instances`)

**Files:**
- Create: `agent_bridge/bridge_tools.py`
- Test: `tests/agent_bridge/test_bridge_tools.py`

**Interfaces:**
- Consumes: `agent_bridge.resolver.Resolver`, upstream `blmcp` `mcp` object (via `blmcp` module after `main()` builds it — but tools must register onto the SAME `FastMCP` instance blmcp uses).
- Produces:
  - `install(resolver: Resolver) -> None` — registers `use_instance` and `list_instances` onto blmcp's FastMCP instance.
  - `use_instance(target: str, pid: int | None = None) -> str` — calls `resolver.set_target`, returns human-readable confirmation.
  - `list_instances() -> list[dict]` — returns `resolver.list_live()` shaped as `{stem, pid, port, blendfile}`.

**Design note on registration:** `blmcp.main()` creates its own `FastMCP("blender-mcp")` locally, so we cannot register onto it from outside. Resolve by having `bridge_server.main()` replicate blmcp's setup: build the `FastMCP`, run blmcp's tool auto-discovery, then register bridge tools, then `mcp.run()`. This means Task 3's `main()` is revised here to inline blmcp's discovery rather than call `blmcp.main()`. (Trade-off accepted: we copy ~8 lines of the discovery loop from `blmcp/__init__.py`; the smoke test guards it. This is the one place we depend on blmcp's internal structure beyond the resolver seam.)

- [ ] **Step 1: Write the failing test**

```python
# tests/agent_bridge/test_bridge_tools.py
from agent_bridge import bridge_tools
from agent_bridge.resolver import Resolver

def _inst(pid, port, stem):
    return {"blender_pid": pid, "port": port, "host": "localhost",
            "blendfile": f"/x/{stem}.blend", "blendfile_stem": stem}

def test_use_instance_sets_target_and_confirms():
    r = Resolver(instances_fn=lambda: [_inst(1, 9877, "resin")])
    msg = bridge_tools._use_instance_impl(r, "resin")
    assert "resin" in msg and "9877" in msg and "1" in msg
    assert r.resolve() == ("localhost", 9877)

def test_list_instances_shape():
    r = Resolver(instances_fn=lambda: [_inst(1, 9877, "resin"), _inst(2, 9878, "dev")])
    rows = bridge_tools._list_instances_impl(r)
    assert {row["stem"] for row in rows} == {"resin", "dev"}
    assert all({"stem", "pid", "port", "blendfile"} <= row.keys() for row in rows)

def test_use_instance_error_is_readable():
    r = Resolver(instances_fn=lambda: [_inst(1, 9877, "resin")])
    msg = bridge_tools._use_instance_impl(r, "nope")
    assert "No live Blender" in msg  # errors returned as text, not raised, for the agent
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/agent_bridge/test_bridge_tools.py -v`
Expected: FAIL — `AttributeError: ... _use_instance_impl`.

- [ ] **Step 3: Write minimal implementation**

```python
# agent_bridge/bridge_tools.py
# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent-facing tools to pick/list the sticky Blender target."""

from .resolver import Resolver, TargetError


def _use_instance_impl(resolver: Resolver, target: str, pid=None) -> str:
    try:
        entry = resolver.set_target(target, pid=pid)
    except TargetError as ex:
        return str(ex)
    return (
        f"Now targeting '{resolver.active_target}' "
        f"(pid {entry.get('blender_pid')}, :{entry.get('port')}). "
        f"All Blender calls in this session go here until you switch."
    )


def _list_instances_impl(resolver: Resolver):
    from . import registry
    rows = []
    for i in resolver.list_live():
        rows.append({
            "stem": registry.stem_of(i),
            "pid": i.get("blender_pid"),
            "port": i.get("port"),
            "blendfile": i.get("blendfile"),
        })
    return rows


def install(mcp, resolver: Resolver) -> None:
    @mcp.tool()
    def use_instance(target: str, pid: int | None = None) -> str:
        """Point this session at the live Blender editing <target> (.blend stem).
        Sticky: all subsequent Blender tool calls go there until changed.
        Pass pid=... to disambiguate when the same file is open twice."""
        return _use_instance_impl(resolver, target, pid=pid)

    @mcp.tool()
    def list_instances() -> list[dict]:
        """List the live Blender instances Agent Bridge can target."""
        return _list_instances_impl(resolver)
```

Note: `install` now takes `mcp` explicitly (see revised `main()` in Step 4).

- [ ] **Step 4: Revise `bridge_server.main()` to build the FastMCP and register both tool sets**

Replace `main()` in `agent_bridge/bridge_server.py` with:

```python
def main() -> int:
    install_patch()

    import importlib
    import os
    import pkgutil
    import yaml
    from mcp.server.fastmcp import FastMCP
    import blmcp
    import blmcp.tools as tools_pkg
    from . import bridge_tools

    data_dir = os.path.join(os.path.dirname(os.path.abspath(blmcp.__file__)), "data")
    with open(os.path.join(data_dir, "prompts.yml"), encoding="utf-8") as fh:
        prompts = yaml.safe_load(fh)

    mcp = FastMCP("agent-bridge", instructions=str(prompts["initial_instructions"]))

    for _importer, modname, _ispkg in pkgutil.iter_modules(tools_pkg.__path__):
        if modname.endswith("_toolcode") or modname.startswith("_template_"):
            continue
        mod = importlib.import_module(f"blmcp.tools.{modname}")
        if hasattr(mod, "register"):
            mod.register(mcp)

    bridge_tools.install(mcp, RESOLVER)
    mcp.run(transport="stdio")
    return 0
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/agent_bridge/test_bridge_tools.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add agent_bridge/bridge_tools.py agent_bridge/bridge_server.py tests/agent_bridge/test_bridge_tools.py
git commit -m "feat(agent-bridge): use_instance + list_instances tools; wire FastMCP"
```

---

### Task 5: Blender-side serve + register operator

Makes each Blender write its live socket + `.blend` stem into the registry so the resolver can find it — independent of Claude Pair's pairing flow.

**Files:**
- Create: `agent_bridge/__init__.py`
- Test: `tests/agent_bridge/test_register_payload.py` (pure-Python part only; operator body is smoke-run manually in Blender).

**Interfaces:**
- Consumes: `agent_bridge.registry.write`, `claude_pair.pair` (`find_free_port`, `start_official_mcp_on_port`, `is_official_mcp_running`).
- Produces:
  - `build_register_payload(pid, port, host, blendfile) -> dict` — pure function returning the registry entry (incl. `blendfile_stem`). Unit-tested.
  - `AGENT_BRIDGE_OT_serve` operator (`agent_bridge.serve`): pick free port → start official MCP server on it → write registry entry.
  - `AGENT_BRIDGE_OT_stop` operator: stop server + remove registry entry.
  - `AGENT_BRIDGE_PT_panel` in the `Claude` category with Serve/Stop + a live-instance readout.
  - `register()` / `unregister()`.

- [ ] **Step 1: Write the failing test (pure payload builder)**

```python
# tests/agent_bridge/test_register_payload.py
from agent_bridge import build_register_payload

def test_payload_has_stem_and_core_fields():
    p = build_register_payload(25591, 9877, "localhost",
                               "/x/no3d asset dev.blend")
    assert p["blender_pid"] == 25591
    assert p["port"] == 9877
    assert p["host"] == "localhost"
    assert p["blendfile"] == "/x/no3d asset dev.blend"
    assert p["blendfile_stem"] == "no3d asset dev"

def test_payload_stem_empty_for_unsaved():
    p = build_register_payload(1, 9877, "localhost", "")
    assert p["blendfile_stem"] == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/agent_bridge/test_register_payload.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_register_payload'`.

- [ ] **Step 3: Write minimal implementation**

```python
# agent_bridge/__init__.py
# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent Bridge — Blender-side serve+register so agents can target this
instance by its .blend filename via the Agent Bridge MCP server."""

__all__ = ("register", "unregister", "build_register_payload")

import os
from pathlib import Path


def build_register_payload(pid: int, port: int, host: str, blendfile: str) -> dict:
    stem = Path(blendfile).stem if blendfile else ""
    return {
        "blender_pid": pid,
        "port": port,
        "host": host,
        "blendfile": blendfile,
        "blendfile_stem": stem,
    }


# --- Blender-only below (guarded so the module imports without bpy for tests) ---
try:
    import bpy
    from bpy.types import Operator, Panel
    _HAS_BPY = True
except ImportError:
    _HAS_BPY = False

if _HAS_BPY:
    from . import registry as reg
    from claude_pair import pair as pair_mod

    _PID = os.getpid()

    class AGENT_BRIDGE_OT_serve(Operator):
        bl_idname = "agent_bridge.serve"
        bl_label = "Serve to Agents"
        bl_description = "Start this Blender's MCP server and register it so agents can target it by .blend name"
        bl_options = {"REGISTER"}

        def execute(self, context):
            del context
            prefs_host = "localhost"
            try:
                if not pair_mod.is_official_mcp_running():
                    port = pair_mod.find_free_port(host=prefs_host)
                    pair_mod.start_official_mcp_on_port(port, host=prefs_host)
                else:
                    port = pair_mod.official_mcp_prefs().port
            except Exception as ex:  # pylint: disable=broad-exception-caught
                self.report({"ERROR"}, f"Could not start MCP server: {ex}")
                return {"CANCELLED"}
            blendfile = bpy.data.filepath or ""
            reg.write(_PID, build_register_payload(_PID, port, prefs_host, blendfile))
            self.report({"INFO"}, f"Serving '{Path(blendfile).stem or '(unsaved)'}' on :{port}")
            return {"FINISHED"}

    class AGENT_BRIDGE_OT_stop(Operator):
        bl_idname = "agent_bridge.stop"
        bl_label = "Stop Serving"
        bl_description = "Stop this Blender's MCP server and remove it from the agent registry"
        bl_options = {"REGISTER"}

        def execute(self, context):
            del context
            try:
                pair_mod.stop_official_mcp()
            except Exception:  # pylint: disable=broad-exception-caught
                pass
            reg.remove(_PID)
            self.report({"INFO"}, "Stopped serving.")
            return {"FINISHED"}

    class AGENT_BRIDGE_PT_panel(Panel):
        bl_idname = "AGENT_BRIDGE_PT_panel"
        bl_label = "Agent Bridge"
        bl_space_type = "VIEW_3D"
        bl_region_type = "UI"
        bl_category = "Claude"

        def draw(self, context):
            del context
            layout = self.layout
            entry = reg.read(_PID)
            if entry:
                layout.label(text=f"Serving :{entry.get('port')}", icon="CHECKMARK")
                layout.label(text=f"As: {entry.get('blendfile_stem') or '(unsaved)'}")
                layout.operator("agent_bridge.stop", icon="UNLINKED")
            else:
                layout.operator("agent_bridge.serve", icon="LINKED")
            layout.separator()
            box = layout.box()
            box.label(text="Live instances (agents can target):", icon="OUTLINER")
            for i in reg.live_instances():
                box.label(text=f"{reg.stem_of(i)}  :{i.get('port')}  pid{i.get('blender_pid')}")

    _classes = (AGENT_BRIDGE_OT_serve, AGENT_BRIDGE_OT_stop, AGENT_BRIDGE_PT_panel)

    def register():
        for cls in _classes:
            bpy.utils.register_class(cls)

    def unregister():
        for cls in reversed(_classes):
            bpy.utils.unregister_class(cls)
else:
    def register():
        raise RuntimeError("agent_bridge Blender side requires bpy")

    def unregister():
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/agent_bridge/test_register_payload.py -v`
Expected: PASS (2 passed). The `try/except ImportError` guard lets the module import without `bpy`.

- [ ] **Step 5: Commit**

```bash
git add agent_bridge/__init__.py tests/agent_bridge/test_register_payload.py
git commit -m "feat(agent-bridge): Blender-side serve+register operator + panel"
```

---

### Task 6: Coupling smoke test (guards the monkeypatch seam)

**Files:**
- Create: `tests/agent_bridge/test_coupling_smoke.py`

**Interfaces:**
- Consumes: upstream `blmcp`, `agent_bridge.bridge_server`.
- Produces: nothing (test-only). Fails loudly if upstream renames/refactors the seam.

- [ ] **Step 1: Write the smoke test**

```python
# tests/agent_bridge/test_coupling_smoke.py
"""Guards the one internal seam Agent Bridge depends on in upstream blmcp.
If this fails after a blmcp upgrade, the monkeypatch no longer lands —
fix the patch before shipping."""
import inspect
import pytest


def test_get_connection_params_exists_zero_arg():
    from blmcp.tools_helpers import connection
    assert hasattr(connection, "get_connection_params")
    sig = inspect.signature(connection.get_connection_params)
    assert len(sig.parameters) == 0


def test_send_code_exists():
    from blmcp.tools_helpers import connection
    assert hasattr(connection, "send_code")


def test_patch_lands_through_send_code():
    """send_code must resolve get_connection_params at call time (unqualified),
    so patching the module attribute is observed."""
    import agent_bridge.bridge_server as b
    from blmcp.tools_helpers import connection

    called = {}

    def fake():
        called["hit"] = True
        return ("localhost", 65500)  # nothing listening -> ConnectionError expected

    orig = connection.get_connection_params
    connection.get_connection_params = fake
    try:
        with pytest.raises(ConnectionError):
            connection.send_code("x", strict_json=False)
        assert called.get("hit"), "send_code did not call the patched get_connection_params"
    finally:
        connection.get_connection_params = orig
```

- [ ] **Step 2: Run the smoke test**

Run: `pytest tests/agent_bridge/test_coupling_smoke.py -v`
Expected: PASS (3 passed). If `test_patch_lands_through_send_code` fails, the patch strategy is broken against the installed blmcp — stop and re-evaluate before proceeding.

- [ ] **Step 3: Commit**

```bash
git add tests/agent_bridge/test_coupling_smoke.py
git commit -m "test(agent-bridge): smoke-guard the blmcp connection seam"
```

---

### Task 7: Packaging + config wiring (console script, pinned dep, README)

**Files:**
- Create: `agent_bridge/pyproject.toml` (or add to repo's existing packaging if present — check first)
- Create: `agent_bridge/README.md`
- Modify: user MCP config guidance (documented, not auto-applied)

**Interfaces:**
- Produces: an installable `agent-bridge` console script → `agent_bridge.bridge_server:main`.

- [ ] **Step 1: Create the packaging file**

```toml
# agent_bridge/pyproject.toml
[project]
name = "agent-bridge"
version = "0.1.0"
description = "Route Claude agent Blender calls to the live instance named by its .blend file"
requires-python = ">=3.12"
dependencies = [
  # Pin to a known-good git ref of upstream blmcp (blender-mcp). Bump deliberately.
  "blender-mcp @ git+https://projects.blender.org/lab/blender_mcp.git@<PINNED_REF>#subdirectory=mcp",
  "pyyaml",
]

[project.scripts]
agent-bridge = "agent_bridge.bridge_server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.backend"
```

Replace `<PINNED_REF>` with the current installed commit. Get it:
```bash
cat /Users/joebowers/.local/share/uv/tools/blender-mcp/uv-receipt.toml
# if it lists a resolved commit, use it; else resolve HEAD of the repo and pin that.
```

- [ ] **Step 2: Install the console script into the tool env**

Run:
```bash
uv tool install --from ./agent_bridge agent-bridge
which agent-bridge
```
Expected: prints a path to the `agent-bridge` executable.

- [ ] **Step 3: Verify the server starts and lists tools**

Run:
```bash
timeout 5 agent-bridge </dev/null || true
python -c "
import agent_bridge.bridge_server as b
b.install_patch()
print('patch installed OK')
"
```
Expected: `patch installed OK` (the `agent-bridge` stdio process will idle waiting for a client; the timeout ending it is fine).

- [ ] **Step 4: Write README with the config-swap instructions**

```markdown
# Agent Bridge

Routes a Claude agent's Blender tool calls to the live Blender instance named
by its open `.blend` file. Sticky per session; switch with `use_instance(...)`.

## Use
1. In each Blender: N-panel > Claude > Agent Bridge > **Serve to Agents**.
2. Point Claude Code's `blender` MCP server at `agent-bridge` instead of `blender-mcp`:
   in `~/.claude.json`, set the `blender` server `command` to the `agent-bridge` path.
3. In chat: `list_instances` to see live Blenders; `use_instance("resin")` to target one.

## Maintenance
- `blender-mcp` is pinned to a git ref in `pyproject.toml`. Bump deliberately.
- After bumping, run `pytest tests/agent_bridge/test_coupling_smoke.py` — it fails
  loudly if the upstream connection seam moved.
```

- [ ] **Step 5: Commit**

```bash
git add agent_bridge/pyproject.toml agent_bridge/README.md
git commit -m "build(agent-bridge): console script, pinned blmcp git dep, README"
```

---

### Task 8: End-to-end integration verification (two Blenders, one agent)

**Files:** none created; this is a manual/scripted verification of the whole system.

- [ ] **Step 1: Set up two Blenders**

Open two Blender instances (per CLAUDE.md, confirm PIDs via `bpy.app.filepath` / `ps -ax | grep Blender.app`). Save each to a distinct `.blend` (e.g. `resin.blend`, `assetdev.blend`). In each: Claude > Agent Bridge > **Serve to Agents**.

- [ ] **Step 2: Confirm both registered on distinct ports**

Run:
```bash
python -c "
from agent_bridge import registry as r
for i in r.live_instances():
    print(r.stem_of(i), i['port'], i['blender_pid'])
"
```
Expected: two rows, distinct ports, correct stems.

- [ ] **Step 3: Drive from one agent via the Bridge MCP**

With Claude Code pointed at `agent-bridge`:
1. `list_instances` → shows both.
2. `use_instance("resin")` → confirmation names resin + its port.
3. `execute_blender_code` creating a uniquely-named empty (e.g. `AB_MARKER_RESIN`).
4. `use_instance("assetdev")` → confirmation names assetdev.
5. `execute_blender_code` creating `AB_MARKER_ASSETDEV`.

- [ ] **Step 4: Verify each marker landed in the correct Blender**

In each Blender (or via a scripted `get_objects_summary` after re-targeting), confirm `AB_MARKER_RESIN` exists ONLY in resin and `AB_MARKER_ASSETDEV` ONLY in assetdev.
Expected: markers are correctly partitioned → routing works end-to-end.

- [ ] **Step 5: Verify restart-resilience (kill the hog problem)**

Close `resin.blend`'s Blender. In the agent: `use_instance("resin")` → expect the clear "no longer live / not live" error (not a silent hang). Reopen resin, Serve again, `use_instance("resin")` → succeeds on whatever new port it got. Confirms no stale-port breakage and no manual disconnect needed.

- [ ] **Step 6: Commit a short verification note**

```bash
# Record the outcome in the project card's activity log (vault), then:
git commit --allow-empty -m "test(agent-bridge): e2e two-Blender routing verified"
```

---

## Self-Review

**1. Spec coverage:**
- §2 problem (port hog/stale) → Task 8 step 5 verifies the fix. ✓
- §3 sticky model → Task 2 resolver (sticky state, survives calls). ✓
- §4 build shape / patch one seam → Task 3 + Task 6 smoke. ✓
- §4 coupling (git-ref pin, patch `get_connection_params` not `send_code`) → Global Constraints + Task 7 pin + Task 6 patch-lands test. ✓
- §5 two halves → Task 5 (Blender register) + Tasks 3–4 (agent side). ✓
- §5 registry superset with `blendfile_stem` → Task 1 + Task 5 payload. ✓
- §6 resolver behavior (0/1/N, default rule, stale) → Task 2 tests cover each branch. ✓
- §7 `use_instance` + `list_instances` → Task 4. ✓
- §7 active-target in memory (mirror to registry) → in-memory: Task 3 `RESOLVER`. **Mirror-to-registry for observability is deferred** — see gap below.
- §10 error handling → resolver messages (Task 2), ConnectionError translation (Task 3). ✓
- §11 testing (unit/smoke/integration/regression) → Tasks 2/6/8; regression (single Blender default) = Task 2 `test_default_single_live_used`. ✓

**Gap found & resolved:** §7's "mirror active target to `~/.blender-pairs/agents/<agent-port>.json` for observability" has no task. This is a nice-to-have (lets the Blender panel show which agent targets what) and is **explicitly out of the v1 critical path** — the resolver's in-memory state is the source of truth. Decision: note it as a **deferred Phase-2 item** rather than pad v1. Added to project card open items. If you want it in v1, it becomes Task 4.5 (best-effort write in `set_target`, best-effort read in the panel).

**2. Placeholder scan:** One intentional placeholder remains — `<PINNED_REF>` in Task 7 Step 1 — with the exact command to resolve it in Step 1. This is a value the engineer must read from the environment at build time, not a design gap. Acceptable.

**3. Type consistency:** `Resolver.set_target`/`resolve`/`list_live`, `registry.stem_of`/`live_instances`, `build_register_payload`, `bridge_tools.install(mcp, resolver)`, `patched_get_connection_params` — names are consistent across Tasks 1–6. `install` signature revised to `(mcp, resolver)` in Task 4 Step 3/4 consistently. ✓
