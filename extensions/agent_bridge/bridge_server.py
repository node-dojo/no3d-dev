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


def build_server():
    """Assemble the agent-bridge FastMCP: patch the seam, auto-discover blmcp's
    tools, then register Agent Bridge's own use_instance/list_instances.

    Split out from main() so the coupling smoke test can exercise the exact
    same discovery/registration path without starting a server (no mcp.run()).
    """
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
    return mcp


def main() -> int:
    mcp = build_server()
    mcp.run(transport="stdio")
    return 0
