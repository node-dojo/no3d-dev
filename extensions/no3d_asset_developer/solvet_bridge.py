from __future__ import annotations

import os
import shutil
import subprocess


def validate_entry(repository: str, source: str) -> tuple[bool, str]:
    cli = os.path.join(repository, "solvet", "cli.js") if repository else ""
    node = shutil.which("node") or "/opt/homebrew/bin/node"
    if not os.path.isfile(cli):
        return False, "Shared SOLVET CLI is unavailable"
    if not os.path.isfile(node):
        return False, "Node is not installed"
    result = subprocess.run(
        [node, cli, "validate", source, "--profile", "workbench", "--json"],
        cwd=repository,
        text=True,
        capture_output=True,
        check=False,
    )
    output = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
    return result.returncode == 0, output
