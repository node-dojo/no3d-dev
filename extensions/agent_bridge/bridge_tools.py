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
