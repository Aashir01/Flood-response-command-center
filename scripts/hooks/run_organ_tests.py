"""PostFileSave hook: run the tests of the organ whose file was just saved (dev profile).

Reads the event JSON on stdin, finds ``organs/<organ>/...`` in it, and runs
``pytest organs/<organ> -x -q``. When the payload has no recognisable path it warns and runs all
organs that exist. Exit code is pytest's (0 also when there are no tests), so a failing test shows
up as a hook warning. Hook-internal errors never fail the session.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import hook_io

TIMEOUT_S = 110  # the hook timeout is 120 s


def organ_dirs(root: Path) -> list[str]:
    organs = root / "organs"
    if not organs.is_dir():
        return []
    return sorted(
        p.name
        for p in organs.iterdir()
        if (p / "pyproject.toml").exists() and (p / "tests").is_dir()
    )


def main() -> int:
    hook_io.configure_streams()
    root = hook_io.REPO_ROOT
    try:
        payload, raw = hook_io.read_event()
        hook_io.log_event("run-organ-tests", raw, root)
        touched = hook_io.organs_from_paths(hook_io.find_paths(payload, root), root)
        available = organ_dirs(root)
        if not touched:
            hook_io.warn("no organ path found in the event; running all organs")
            touched = available
        targets = [f"organs/{o}" for o in touched if o in available]
        if not targets:
            print("run_organ_tests: no organ with tests yet, nothing to run")
            return 0
        res = subprocess.run(
            [sys.executable, "-m", "pytest", *targets, "-x", "-q", "-p", "no:cacheprovider"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        hook_io.warn(f"organ tests exceeded {TIMEOUT_S}s")
        return 1
    except Exception as exc:  # hook bugs must not break the session
        hook_io.warn(f"run_organ_tests failed to run: {exc!r}")
        return 0
    print(hook_io.tail(res.stdout + res.stderr))
    return 0 if res.returncode in (0, 5) else 1


if __name__ == "__main__":
    raise SystemExit(main())
