# SPDX-License-Identifier: GPL-3.0-or-later
"""Detached helper that waits for Blender to exit and opens its saved iteration."""

import argparse
import os
import subprocess
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--app", required=True)
    parser.add_argument("--blend", required=True)
    args = parser.parse_args()

    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            os.kill(args.pid, 0)
        except ProcessLookupError:
            break
        except PermissionError:
            pass
        time.sleep(0.25)
    else:
        raise SystemExit("Blender did not exit within 120 seconds")

    blend = Path(args.blend)
    if not blend.is_file():
        raise SystemExit(f"Saved Blender file is missing: {blend}")
    subprocess.Popen(
        ["open", "-n", "-a", args.app, "--args", str(blend)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


if __name__ == "__main__":
    main()
