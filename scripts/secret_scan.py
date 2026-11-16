"""Local secret scanner (BOOT-R6.4). Complements gitleaks, which runs in CI.

Usage:
    python scripts/secret_scan.py --all            # every tracked or unignored file
    python scripts/secret_scan.py --staged         # staged files, read from the index
    python scripts/secret_scan.py path [path ...]  # explicit files

Exit 0 when clean, 1 when findings exist. Matches are printed redacted.

Ruleset (see RULES):
  aws-access-key, aws-secret-key, github-token (ghp_/gho_/ghu_/ghs_/ghr_), github-pat
  (github_pat_), anthropic-key (sk-ant-), openai-key (sk-), private-key (PEM header),
  azure-speech-key (AZURE_SPEECH_KEY=...), google-service-account (JSON markers),
  generic-secret (api_key/secret/token/password assignment with a high-entropy value),
  env-file (a tracked .env or .env.* file other than .env.example).

Allowlist: a line containing ``secret-scan: allow`` (usually as a comment) is skipped.
Test fixtures should still build positive samples at runtime instead of using the allow marker.
"""

from __future__ import annotations

import argparse
import io
import math
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ALLOW_MARKER = "secret-scan: allow"
MAX_BYTES = 1_000_000
SKIP_DIRS = {".git", ".venv", "node_modules", ".next", "__pycache__", ".stitch-hook-debug"}
SKIP_NAMES = {"uv.lock", "package-lock.json"}

ENTROPY_MIN = 3.5
PLACEHOLDER_RE = re.compile(
    r"(\$\{|\{\{|<[a-z_ -]+>|changeme|change_me|example|your[_-]|xxxx|placeholder|dummy|"
    r"redacted|os\.environ|getenv|process\.env|\*{3,})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    group: int = 0  # capture group holding the secret (for entropy and redaction)
    entropy: bool = False  # require entropy >= ENTROPY_MIN on the group


def _r(name: str, pattern: str, group: int = 0, entropy: bool = False) -> Rule:
    return Rule(name, re.compile(pattern), group, entropy)


RULES: tuple[Rule, ...] = (
    _r("aws-access-key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    _r(
        "aws-secret-key",
        r"(?i)aws_?secret_?access_?key[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9/+=]{40})\b",
        1,
        True,
    ),
    _r("github-token", r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    _r("github-pat", r"\bgithub_pat_[A-Za-z0-9_]{22,}\b"),
    _r("anthropic-key", r"\bsk-ant-[A-Za-z0-9_\-]{20,}"),
    _r("openai-key", r"\bsk-(?!ant-)(?:proj-|svcacct-)?[A-Za-z0-9_\-]{20,}"),
    _r("private-key", r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"),
    _r(
        "azure-speech-key",
        r"AZURE_SPEECH_KEY[\"']?\s*[:=]\s*[\"']?([0-9a-fA-F]{32}|[A-Za-z0-9+/]{40,}={0,2})(?![A-Za-z0-9])",
        1,
    ),
    _r("google-service-account", r"\"type\"\s*:\s*\"service_account\""),
    _r("google-service-account", r"\"private_key_id\"\s*:\s*\"[0-9a-f]{20,}\""),
    _r(
        "generic-secret",
        r"(?i)(?:api[_-]?key|secret|token|passwd|password)[\"']?\s*[:=]\s*[\"']([^\"'\s]{16,})[\"']",
        1,
        True,
    ),
    _r(
        "generic-secret",
        r"(?m)^\s*(?:export\s+)?[A-Z0-9_]*(?:API_?KEY|SECRET|TOKEN|PASSWORD)[A-Z0-9_]*=([^\s\"'#]{16,})\s*$",
        1,
        True,
    ),
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    snippet: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: [{self.rule}] {self.snippet}"


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for ch in value:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(value)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def _redact(value: str) -> str:
    return value[:4] + "***" if len(value) > 4 else "***"


def is_env_file(path: str) -> bool:
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return (name == ".env" or name.startswith(".env.")) and name != ".env.example"


def scan_text(text: str, path: str = "<text>") -> list[Finding]:
    """Scan one file's text. Lines carrying the allow marker are skipped."""
    findings: list[Finding] = []
    lines = text.splitlines()
    allowed = {i for i, ln in enumerate(lines, 1) if ALLOW_MARKER in ln}
    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line_no = text.count("\n", 0, m.start()) + 1
            if line_no in allowed:
                continue
            secret = m.group(rule.group)
            if rule.entropy and (
                shannon_entropy(secret) < ENTROPY_MIN or PLACEHOLDER_RE.search(secret)
            ):
                continue
            findings.append(Finding(path, line_no, rule.name, _redact(secret)))
    return sorted(set(findings), key=lambda f: (f.path, f.line, f.rule))


def scan_path_name(path: str) -> list[Finding]:
    if is_env_file(path):
        return [Finding(path, 0, "env-file", "environment file must not be committed")]
    return []


def _looks_binary(data: bytes) -> bool:
    return b"\x00" in data[:4096]


def scan_bytes(data: bytes, path: str) -> list[Finding]:
    findings = scan_path_name(path)
    if len(data) > MAX_BYTES or _looks_binary(data):
        return findings
    return findings + scan_text(data.decode("utf-8", errors="replace"), path)


def _git(args: list[str], root: Path) -> bytes:
    res = subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {res.stderr.decode(errors='replace')}")
    return res.stdout


def _skip(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    return bool(SKIP_DIRS.intersection(parts)) or parts[-1] in SKIP_NAMES


def list_all(root: Path) -> list[str]:
    out = _git(["ls-files", "-z", "--cached", "--others", "--exclude-standard"], root)
    return [p for p in out.decode("utf-8").split("\0") if p and not _skip(p)]


def list_staged(root: Path) -> list[str]:
    out = _git(["diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"], root)
    return [p for p in out.decode("utf-8").split("\0") if p and not _skip(p)]


def scan_files(root: Path, paths: Iterable[str], *, staged: bool = False) -> list[Finding]:
    findings: list[Finding] = []
    for rel in paths:
        try:
            data = _git(["show", f":{rel}"], root) if staged else (root / rel).read_bytes()
        except (OSError, RuntimeError):
            continue
        findings.extend(scan_bytes(data, rel.replace("\\", "/")))
    return findings


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Scan files for secrets.")
    parser.add_argument("--all", action="store_true", help="scan all tracked/unignored files")
    parser.add_argument("--staged", action="store_true", help="scan staged files")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)
    root: Path = args.root

    if args.staged:
        findings = scan_files(root, list_staged(root), staged=True)
    elif args.all:
        findings = scan_files(root, list_all(root))
    elif args.paths:
        findings = scan_files(root, args.paths)
    else:
        parser.error("give --all, --staged or paths")
    if findings:
        print(f"secret_scan: {len(findings)} finding(s)", file=sys.stderr)
        for f in findings:
            print(f"  {f}", file=sys.stderr)
        print(f"Add '# {ALLOW_MARKER}' to a line only for non-secret test data.", file=sys.stderr)
        return 1
    print("secret_scan: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
