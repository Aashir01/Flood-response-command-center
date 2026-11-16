"""PostFileSave hook: validate the MCP contracts after a server, model or contract file changed.

Runs ``scripts/check_contracts.py`` and passes its output and exit code through. The event
payload is only logged; the check always covers the whole contract.
"""

from __future__ import annotations

import subprocess
import sys

import hook_io

TIMEOUT_S = 25  # the hook timeout is 30 s


def main() -> int:
    hook_io.configure_streams()
    root = hook_io.REPO_ROOT
    try:
        _, raw = hook_io.read_event()
        hook_io.log_event("on-save-contracts", raw, root)
        res = subprocess.run(
            [sys.executable, str(root / "scripts" / "check_contracts.py")],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        hook_io.warn(f"check_contracts exceeded {TIMEOUT_S}s")
        return 1
    except Exception as exc:
        hook_io.warn(f"on_save_contracts failed to run: {exc!r}")
        return 0
    print(hook_io.tail(res.stdout + res.stderr, 60))
    return res.returncode


if __name__ == "__main__":
    raise SystemExit(main())
