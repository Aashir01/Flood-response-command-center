"""Lint and secret-scan the staged files before a commit.

Two entry points share this code:

* Kiro ``PreToolUse`` hook on ``shell``: reads the event JSON on stdin and acts only when the
  command contains ``git commit``. Exit 2 blocks the tool call.
* The git ``pre-commit`` hook (``scripts/hooks/git-pre-commit``) calls it with ``--git``, which
  skips event parsing. A non-zero exit aborts the commit.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts/ for secret_scan
import hook_io
import secret_scan

BLOCK = 2


def _run(cmd: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def lint_staged(root: Path, files: list[str]) -> list[str]:
    """Run ruff check and format --check on staged Python files. Returns problem texts."""
    py = [f for f in files if f.endswith(".py") and (root / f).exists()]
    if not py:
        return []
    problems: list[str] = []
    for label, args in (("ruff check", ["check"]), ("ruff format --check", ["format", "--check"])):
        res = _run([sys.executable, "-m", "ruff", *args, *py], root)
        if res.returncode == 0:
            continue
        if "No module named ruff" in res.stderr:
            hook_io.warn("ruff is not installed in this interpreter; skipping lint")
            return problems
        problems.append(f"{label} failed:\n{res.stdout}{res.stderr}".rstrip())
    return problems


def guard(root: Path) -> list[str]:
    staged = secret_scan.list_staged(root)
    problems = lint_staged(root, staged)
    findings = secret_scan.scan_files(root, staged, staged=True)
    if findings:
        problems.append("secret scan found:\n" + "\n".join(f"  {f}" for f in findings))
    return problems


def main(argv: list[str] | None = None) -> int:
    hook_io.configure_streams()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--git", action="store_true", help="called from the git pre-commit hook")
    parser.add_argument("--root", type=Path, default=hook_io.REPO_ROOT)
    args = parser.parse_args(argv)

    if not args.git:
        payload, raw = hook_io.read_event()
        hook_io.log_event("pre-commit-guard", raw, args.root)
        command = hook_io.find_command(payload)
        if command is None and payload is None and raw:
            command = raw
        if not hook_io.is_git_commit(command):
            return 0

    try:
        problems = guard(args.root)
    except Exception as exc:  # a broken guard must not wedge the session
        hook_io.warn(f"guard error: {exc!r}")
        return 0 if not args.git else 1
    if problems:
        print("pre-commit guard blocked the commit:\n", file=sys.stderr)
        for p in problems:
            print(p + "\n", file=sys.stderr)
        return BLOCK
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
