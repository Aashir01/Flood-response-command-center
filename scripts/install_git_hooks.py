"""Install the repo's git hooks (currently ``pre-commit``) into the repo's hooks directory.

Usage: python scripts/install_git_hooks.py [--force] [--root PATH]

Idempotent. An existing pre-commit hook that this script did not install is left alone unless
``--force`` is given, in which case it is saved as ``pre-commit.bak``.
"""

from __future__ import annotations

import argparse
import io
import stat
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path("scripts") / "hooks" / "git-pre-commit"
MARKER = "stitch-managed pre-commit hook"


def hooks_path(root: Path) -> Path:
    res = subprocess.run(
        ["git", "rev-parse", "--git-path", "hooks"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    p = Path(res.stdout.strip())
    return p if p.is_absolute() else root / p


def install(root: Path, force: bool = False) -> str:
    """Install the hook. Returns 'installed', 'unchanged' or 'refused'."""
    content = (root / SOURCE).read_bytes().replace(b"\r\n", b"\n")
    dest_dir = hooks_path(root)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "pre-commit"
    if dest.exists():
        existing = dest.read_bytes()
        if existing == content:
            return "unchanged"
        if MARKER.encode() not in existing:
            if not force:
                return "refused"
            dest.replace(dest_dir / "pre-commit.bak")
    dest.write_bytes(content)  # LF endings: Git for Windows' sh rejects CRLF scripts
    dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return "installed"


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Install git hooks.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    result = install(args.root, args.force)
    if result == "refused":
        print(
            "install_git_hooks: a different pre-commit hook exists; use --force to replace it",
            file=sys.stderr,
        )
        return 1
    print(f"install_git_hooks: pre-commit {result} in {hooks_path(args.root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
