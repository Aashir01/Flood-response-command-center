"""Repository hygiene checks (deployment design section 12). Stdlib only.

    python deploy/bin/check_repo_hygiene.py [--root PATH] [--third-party advisory|strict|off]

Checks, each failing with one clear line:

* ``.kiro`` is tracked and never ignored (DEP-P3, DEP-R5.2, DEP-R8.2).
* ``.kiro/settings/mcp.json`` holds no credential-looking value; ``${VAR}`` references pass (R8.3).
* ``.env``, ``prod.env`` and ``deploy/secrets/**`` are not tracked (DEP-P2, R3.3).
* every tracked file under ``data/demo/`` is listed in a ``MANIFEST.md`` (R8.1).
* ``LICENSE`` (MIT), ``README.md``, ``THIRD_PARTY.md``, ``docs/kiro-writeup.md`` and
  ``deploy/README.md`` exist (R8.1, R9).
* best effort: every direct dependency in a ``pyproject.toml`` or ``package.json`` is named in
  ``THIRD_PARTY.md`` or ``deploy/third_party_allow.txt`` (R5.3). Advisory by default.

Exit 0 when clean, 1 on any failure.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterable, Iterator
from pathlib import Path, PurePosixPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
KIRO_PARTS = ("steering", "specs", "hooks", "agents", "settings")
REQUIRED_FILES = (
    "LICENSE",
    "README.md",
    "THIRD_PARTY.md",
    "docs/kiro-writeup.md",
    "deploy/README.md",
)
SECRET_FILE_RE = re.compile(
    r"(^|/)(\.env|prod\.env)$|(^|/)\.env\.(?!example$)[^/]+$|^deploy/secrets/"
)
ENV_REF_RE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*(:-[^}]*)?\}$|^\$[A-Za-z_][A-Za-z0-9_]*$")
SECRETISH_KEY_RE = re.compile(
    r"(api[_-]?key|token|secret|password|passwd|authorization|bearer)", re.I
)
CREDENTIAL_VALUE_RES = (
    re.compile(r"sk-(ant-)?[A-Za-z0-9_-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"xox[abpr]-[A-Za-z0-9-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)bearer\s+(?!\$\{)[A-Za-z0-9._~+/-]{16,}"),
)
MANIFEST_SKIP = {".gitkeep", "MANIFEST.md"}
GLOB_TOKEN_RE = re.compile(r"[\w./-]*\*[\w./*-]*")


def git(root: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
    )


def tracked(root: Path, *paths: str) -> list[str]:
    res = git(root, "ls-files", "-z", "--", *paths)
    return [p for p in res.stdout.split("\0") if p]


# --- .kiro ---------------------------------------------------------------------------------------


def _gitignore_matches_kiro(line: str) -> bool:
    raw = line.strip()
    if not raw or raw.startswith("#") or raw.startswith("!"):
        return False
    pat = raw.rstrip("/").lstrip("/")
    for candidate in (".kiro", ".kiro/x"):
        if PurePosixPath(candidate).match(pat) or pat in (".kiro", ".kiro/", ".kiro/*", ".kiro/**"):
            return True
    return pat.startswith(".kiro") or pat in ("*", "**", ".*", ".k*")


def check_kiro(root: Path) -> list[str]:
    problems: list[str] = []
    # --no-index: also catch a rule that would ignore .kiro although its files are tracked
    if git(root, "check-ignore", "-q", "--no-index", ".kiro").returncode == 0:
        problems.append(".kiro: `git check-ignore .kiro` matches; .kiro must never be ignored")
    for path in tracked(root, "*.gitignore", ".gitignore"):
        text = (root / path).read_text(encoding="utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            if _gitignore_matches_kiro(line):
                problems.append(f".kiro: {path}:{n} `{line.strip()}` would ignore .kiro")
    files = tracked(root, ".kiro")
    if not files:
        problems.append(".kiro: no tracked files under .kiro (git ls-files .kiro is empty)")
    else:
        present = {f.split("/")[1] for f in files if f.count("/") >= 2}
        missing = [p for p in KIRO_PARTS if p not in present]
        if missing:
            problems.append(f".kiro: tracked tree lacks {', '.join(missing)}")
    return problems


# --- MCP settings --------------------------------------------------------------------------------


def _walk(obj: Any, path: str = "") -> Iterator[tuple[str, str, str]]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        key = path.rsplit(".", 1)[-1]
        yield path, key, obj


def check_mcp_settings(root: Path) -> list[str]:
    p = root / ".kiro" / "settings" / "mcp.json"
    if not p.exists():
        return []
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"mcp.json: not valid JSON ({exc.msg} at line {exc.lineno})"]
    problems: list[str] = []
    for path, key, value in _walk(doc):
        v = value.strip()
        if not v:
            continue
        if any(rx.search(v) for rx in CREDENTIAL_VALUE_RES):
            problems.append(f"mcp.json: {path} looks like a credential; use a ${{VAR}} reference")
            continue
        # "Authorization": "Bearer ${GITHUB_TOKEN}" is fine; a literal value is not.
        if SECRETISH_KEY_RE.search(key) and not ENV_REF_RE.match(v) and "${" not in v:
            problems.append(f"mcp.json: {path} holds a literal secret-like value")
    return problems


# --- tracked secret files ------------------------------------------------------------------------


def check_secret_files(root: Path) -> list[str]:
    return [
        f"secrets: {path} is tracked; it must stay git-ignored"
        for path in tracked(root)
        if SECRET_FILE_RE.search(path)
    ]


# --- data/demo MANIFEST coverage -----------------------------------------------------------------


def _manifests(root: Path, files: Iterable[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for f in files:
        if PurePosixPath(f).name == "MANIFEST.md":
            out[str(PurePosixPath(f).parent)] = (root / f).read_text(
                encoding="utf-8", errors="replace"
            )
    return out


def _covered(path: str, manifests: dict[str, str]) -> bool:
    p = PurePosixPath(path)
    for d in [str(a) for a in p.parents]:
        text = manifests.get(d)
        if text is None:
            continue
        rel = str(p.relative_to(d))
        # listed by relative path, by file name, or by a parent directory ("recorded/", "pack/")
        if rel in text or p.name in text:
            return True
        parts = PurePosixPath(rel).parts
        for i in range(1, len(parts)):
            prefix = "/".join(parts[:i])
            if re.search(rf"(?<![\w/.-]){re.escape(prefix)}/(?![\w.*-])", text):
                return True
        # glob rows such as `recorded/library/**` (fnmatch's `*` also matches `/`)
        if any(fnmatch.fnmatchcase(rel, g) for g in GLOB_TOKEN_RE.findall(text)):
            return True
    return False


def check_manifest(root: Path) -> list[str]:
    files = tracked(root, "data/demo")
    if not files:
        return []
    manifests = _manifests(root, files)
    if "data/demo" not in manifests:
        return ["manifest: data/demo/MANIFEST.md is missing"]
    return [
        f"manifest: {f} is not listed in any data/demo MANIFEST.md (source and license)"
        for f in files
        if PurePosixPath(f).name not in MANIFEST_SKIP and not _covered(f, manifests)
    ]


# --- required files ------------------------------------------------------------------------------


def check_required(root: Path) -> list[str]:
    problems = [f"files: {f} is missing" for f in REQUIRED_FILES if not (root / f).is_file()]
    lic = root / "LICENSE"
    if lic.is_file() and "MIT License" not in lic.read_text(encoding="utf-8", errors="replace"):
        problems.append("files: LICENSE is not the MIT license text")
    return problems


# --- THIRD_PARTY (best effort) -------------------------------------------------------------------


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _req_name(spec: str) -> str:
    m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", spec)
    return m.group(1) if m else ""


def direct_dependencies(root: Path) -> dict[str, set[str]]:
    deps: dict[str, set[str]] = {}
    for path in tracked(root, "*pyproject.toml"):
        if path.startswith(".kiro/"):
            continue
        try:
            doc = tomllib.loads((root / path).read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        proj = doc.get("project", {})
        specs = list(proj.get("dependencies", []))
        for extra in proj.get("optional-dependencies", {}).values():
            specs += extra
        for spec in specs:
            name = _req_name(spec)
            if name and not name.startswith("stitch"):
                deps.setdefault(_norm(name), set()).add(path)
    for path in tracked(root, "*package.json"):
        if "node_modules/" in path or path.startswith(".kiro/"):
            continue
        try:
            doc = json.loads((root / path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for section in ("dependencies", "devDependencies"):
            for name in doc.get(section, {}):
                deps.setdefault(_norm(name), set()).add(path)
    return deps


def check_third_party(root: Path) -> list[str]:
    tp = root / "THIRD_PARTY.md"
    if not tp.is_file():
        return []
    raw = tp.read_text(encoding="utf-8", errors="replace")
    text = _norm(raw) + "\n" + re.sub(r"[^a-z0-9]", "", raw.lower())  # "OR-Tools" ~ ortools
    allow_file = root / "deploy" / "third_party_allow.txt"
    allowed: set[str] = set()
    if allow_file.is_file():
        for line in allow_file.read_text(encoding="utf-8").splitlines():
            name = line.split("#", 1)[0].strip()
            if name:
                allowed.add(_norm(name))
    problems = []
    for name, sources in sorted(direct_dependencies(root).items()):
        bare = name.split("/")[-1]
        compact = re.sub(r"[^a-z0-9]", "", bare)
        if name in allowed or name in text or bare in text or compact in text:
            continue
        problems.append(
            f"third-party: {name} ({', '.join(sorted(sources))}) has no THIRD_PARTY.md row"
        )
    return problems


# --- entry ---------------------------------------------------------------------------------------


def run(root: Path, third_party: str = "advisory") -> tuple[list[str], list[str]]:
    """Return (failures, advisories)."""
    failures = [
        *check_kiro(root),
        *check_mcp_settings(root),
        *check_secret_files(root),
        *check_manifest(root),
        *check_required(root),
    ]
    advisories: list[str] = []
    if third_party != "off":
        tp = check_third_party(root)
        (failures if third_party == "strict" else advisories).extend(tp)
    return failures, advisories


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stitch repository hygiene checks")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--third-party", choices=["advisory", "strict", "off"], default="advisory")
    args = parser.parse_args(argv)
    failures, advisories = run(args.root, args.third_party)
    for line in advisories:
        print(f"advisory: {line}")
    for line in failures:
        print(f"FAIL: {line}")
    if failures:
        print(f"repo hygiene: {len(failures)} failure(s)")
        return 1
    print("repo hygiene: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
