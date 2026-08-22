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


def _extract_port(entry: dict, target_stem: str) -> int:
    """Extract port from registry entry, raising TargetError if malformed."""
    try:
        port = entry["port"]
        return int(port)
    except (KeyError, ValueError, TypeError) as e:
        raise TargetError(
            f"Registry entry for '{target_stem}' is malformed or incomplete: "
            f"missing or invalid 'port' field."
        ) from e


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
                stem = registry.stem_of(e)
                return e.get("host", "localhost"), _extract_port(e, stem)
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
        stem = registry.stem_of(e)
        return e.get("host", "localhost"), _extract_port(e, stem)
