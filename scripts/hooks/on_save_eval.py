"""PostFileSave hook: refresh the fast eval results for the touched organ.

Runs ``python -m evals.run --organ <organ> --fast --seed 0`` (``--organ all`` when the payload
names no organ), which rewrites ``evals/results/<organ>.json`` and ``latest.json``.
"""

from __future__ import annotations

import subprocess
import sys

import hook_io

TIMEOUT_S = 110  # the hook timeout is 120 s


def main() -> int:
    hook_io.configure_streams()
    root = hook_io.REPO_ROOT
    try:
        if not (root / "evals" / "run.py").exists():
            hook_io.warn("evals/run.py not found; skipping")
            return 0
        payload, raw = hook_io.read_event()
        hook_io.log_event("on-save-eval", raw, root)
        organs = hook_io.organs_from_paths(hook_io.find_paths(payload, root), root)
        targets = organs or ["all"]
        for organ in targets:
            res = subprocess.run(
                [sys.executable, "-m", "evals.run", "--organ", organ, "--fast", "--seed", "0"],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=TIMEOUT_S,
                check=False,
            )
            print(hook_io.tail(res.stdout + res.stderr, 20))
            if res.returncode != 0:
                return 1
    except subprocess.TimeoutExpired:
        hook_io.warn(f"eval run exceeded {TIMEOUT_S}s")
        return 1
    except Exception as exc:
        hook_io.warn(f"on_save_eval failed to run: {exc!r}")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
