#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Detached relaunch helper for Save & Reload.

Run as a standalone interpreter (NOT from Blender's embedded python):

    python3 helper.py --pid <pid> --app <Blender.app bundle> --blend <file.blend>

Behavior:
  1. Poll until <pid> is gone (signal 0 returns OSError once the process dies).
  2. Once dead, exec `open -n -a <app bundle> --args <blend file>` to relaunch.

The parent (the add-on operator) detaches us via subprocess.Popen with
start_new_session=True and stdin/stdout/stderr → /dev/null so this script
survives Blender's death.

Errors are written to ~/Library/Logs/save_and_reload-helper.log on a best-effort
basis. The helper otherwise emits no output — it has no terminal.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


LOG_PATH = Path.home() / "Library" / "Logs" / "save_and_reload-helper.log"
POLL_INTERVAL_SEC = 0.25
MAX_WAIT_SEC = 120  # safety cap; quitting Blender should take << this


def _log(msg: str) -> None:
    """Best-effort append to the helper log. Never raises."""
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"[{ts}] pid={os.getpid()} {msg}\n")
    except Exception:
        pass


def _process_alive(pid: int) -> bool:
    """Return True if the given pid is still alive."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we can't signal it; treat as alive.
        return True
    except OSError:
        return False
    return True


def _wait_for_exit(pid: int, max_wait: float = MAX_WAIT_SEC) -> bool:
    """Wait until pid exits. Returns True if it exited within max_wait."""
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        if not _process_alive(pid):
            return True
        time.sleep(POLL_INTERVAL_SEC)
    return False


def _relaunch(app_bundle: str, blend_path: str) -> int:
    """Spawn a new instance of the Blender.app bundle with the blend file.

    Uses `open -n -a <bundle> --args <blend>` — the `-n` flag forces a new
    instance even if other Blender instances of the same version are running.
    Returns the subprocess return code.
    """
    cmd = ["open", "-n", "-a", app_bundle, "--args", blend_path]
    _log(f"relaunch cmd: {cmd}")
    try:
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except Exception as ex:  # noqa: BLE001
        _log(f"relaunch FAILED: {ex}")
        return 1
    if result.returncode != 0:
        _log(f"relaunch returned {result.returncode}: "
             f"stdout={result.stdout!r} stderr={result.stderr!r}")
    else:
        _log("relaunch ok")
    return result.returncode


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="save_and_reload-helper",
        description=(
            "Wait for a Blender PID to exit, then relaunch Blender.app "
            "with a specific .blend file. macOS only."
        ),
    )
    parser.add_argument(
        "--pid", type=int, required=True,
        help="PID of the Blender instance to wait on",
    )
    parser.add_argument(
        "--app", type=str, required=True,
        help="Path to the Blender.app bundle to relaunch",
    )
    parser.add_argument(
        "--blend", type=str, required=True,
        help="Path to the .blend file to open in the relaunched Blender",
    )
    parser.add_argument(
        "--max-wait", type=float, default=MAX_WAIT_SEC,
        help=f"Max seconds to wait for the PID to exit (default {MAX_WAIT_SEC})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    _log(f"start: pid={args.pid} app={args.app!r} blend={args.blend!r}")

    if not _wait_for_exit(args.pid, max_wait=args.max_wait):
        _log(f"timeout waiting for pid {args.pid} — aborting relaunch")
        return 2

    # Tiny extra grace period so macOS releases any window-server locks
    # before we ask `open -n` for a fresh instance.
    time.sleep(0.5)

    return _relaunch(args.app, args.blend)


if __name__ == "__main__":
    sys.exit(main())
