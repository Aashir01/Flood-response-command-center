"""Tolerant reader for Kiro command-hook events (JSON on stdin).

The key that carries the saved file path is not documented, so this module scans the payload for
anything that looks like a repo path and logs the raw payload to ``.stitch-hook-debug/`` (git
ignored). Read that file after the first real event and hard-code the real shape.

Rules for hook scripts built on this module (BOOT-R6.2): never crash on odd payloads, warn on
stderr, exit non-zero only for real failures (tests failing, contract drift, secrets found).
"""

from __future__ import annotations

import io
import json
import re
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEBUG_DIR = ".stitch-hook-debug"
PATH_KEYS = (
    "file_path",
    "filePath",
    "path",
    "file",
    "filename",
    "uri",
    "target",
)
PATH_LIKE = re.compile(r"[\w.\-/\\: ]+\.[A-Za-z0-9]{1,8}$")
GIT_COMMIT = re.compile(
    r"(^|[\s;&|(])git\s+(?:(?:-C|-c|--git-dir|--work-tree)\s+\S+\s+|-[^\s]+\s+)*commit\b"
)


def configure_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")


def warn(message: str) -> None:
    print(f"[stitch-hook] warning: {message}", file=sys.stderr)


def read_event(stream: io.TextIOBase | None = None) -> tuple[Any, str]:
    """Return ``(parsed_json_or_None, raw_text)``. Never raises on bad input."""
    src = stream if stream is not None else sys.stdin
    try:
        if src is sys.stdin and sys.stdin is not None and sys.stdin.isatty():
            return None, ""
        raw = src.read()
    except (OSError, ValueError):
        return None, ""
    if not raw.strip():
        return None, raw
    try:
        return json.loads(raw), raw
    except json.JSONDecodeError:
        warn("event on stdin is not JSON; treating it as plain text")
        return None, raw


def log_event(name: str, raw: str, root: Path = REPO_ROOT) -> None:
    """Write the raw payload to ``.stitch-hook-debug/<name>.last.json`` (best effort)."""
    try:
        d = root / DEBUG_DIR
        d.mkdir(exist_ok=True)
        stamp = datetime.now(UTC).isoformat()
        (d / f"{name}.last.json").write_text(
            json.dumps({"received_at": stamp, "raw": raw}, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        warn(f"could not write debug log: {exc}")


def _walk_strings(node: Any, key: str | None = None) -> Iterator[tuple[str | None, str]]:
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk_strings(v, str(k))
    elif isinstance(node, list):
        for v in node:
            yield from _walk_strings(v, key)
    elif isinstance(node, str):
        yield key, node


def normalize_repo_path(value: str, root: Path = REPO_ROOT) -> str | None:
    """Return a repo-relative POSIX path, or None if ``value`` is not inside the repo."""
    text = value.strip()
    if text.startswith("file:///"):
        text = text[len("file:///") :]
    elif text.startswith("file://"):
        text = text[len("file://") :]
    text = text.replace("\\", "/")
    if not text or "\n" in text or len(text) > 500:
        return None
    root_posix = root.resolve().as_posix()
    if text.lower().startswith(root_posix.lower() + "/"):
        text = text[len(root_posix) + 1 :]
    elif re.match(r"^(/|[A-Za-z]:/)", text):
        return None  # absolute path outside the repo
    text = text.removeprefix("./")
    if ".." in text.split("/") or not PATH_LIKE.search(text):
        return None
    return text


def find_paths(payload: Any, root: Path = REPO_ROOT) -> list[str]:
    """Repo-relative paths found in the payload, preferred keys first, de-duplicated."""
    preferred: list[str] = []
    others: list[str] = []
    for key, value in _walk_strings(payload):
        norm = normalize_repo_path(value, root)
        if norm is None:
            continue
        (preferred if key in PATH_KEYS else others).append(norm)
    seen: dict[str, None] = {}
    for p in [*preferred, *others]:
        seen.setdefault(p, None)
    return list(seen)


def find_command(payload: Any) -> str | None:
    """The shell command of a PreToolUse event, if one can be found."""
    for key, value in _walk_strings(payload):
        if key in ("command", "cmd", "commandLine"):
            return value
    return None


def is_git_commit(command: str | None) -> bool:
    return bool(command and GIT_COMMIT.search(command))
