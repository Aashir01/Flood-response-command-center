"""BOOT-P7 and the pre-commit guard. Positive samples are built at runtime from fragments so this
file never contains a secret-shaped literal (the scanner runs over the test sources in CI)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import hook_io
import pre_commit_guard
import pytest
from hypothesis import given
from hypothesis import strategies as st
from install_git_hooks import install
from secret_scan import REPO_ROOT, scan_bytes, scan_text, shannon_entropy

HIGH = "Zx9Qw8Er7Ty6Ui5Op4As3Df2Gh1Jk0LmNb"  # 34 mixed chars, entropy > 4

POSITIVE: dict[str, str] = {
    "aws-access-key": "id = " + "AKIA" + "QWERTYUIOPASDFGH",
    "aws-secret-key": "aws_secret_access_key = '"
    + "wJalrXUtnFEMI/K7MDEN"
    + "bPxRfiCYzq8Wv2Lm5T9A"
    + "'",
    "github-token": "token: " + "gh" + "p_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8",
    "github-pat": "x " + "github" + "_pat_" + "11ABCDEFG0abcdefghijkl_" + HIGH,
    "anthropic-key": "k=" + "sk" + "-ant-" + "api03-" + HIGH,
    "openai-key": "OPENAI " + "sk" + "-" + HIGH,
    "private-key": "-----BEGIN " + "RSA PRIVATE" + " KEY-----",
    "azure-speech-key": "AZURE_SPEECH" + "_KEY=" + "0123456789abcdef0123456789abcdef",
    "google-service-account": '{"type": "' + "service" + '_account"}',
    "generic-secret": 'api_key = "' + HIGH + '"',
}

POSITIVE_ALT: list[tuple[str, str]] = [
    ("generic-secret", "SECRET_" + "TOKEN=" + HIGH),
    ("generic-secret", '"pass' + 'word": "' + HIGH + '"'),
    ("private-key", "-----BEGIN " + "OPENSSH PRIVATE" + " KEY-----"),
    ("private-key", "-----BEGIN " + "PRIVATE" + " KEY-----"),
    (
        "azure-speech-key",
        "AZURE_SPEECH" + '_KEY = "' + "Zx9Qw8Er7Ty6Ui5Op4As3Df2Gh1Jk0LmNbVc7Xz1" + '"',
    ),
    ("anthropic-key", "sk" + "-ant-" + "x" * 8 + HIGH),
    ("github-token", "gh" + "o_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"),
]

CLEAN: list[str] = [
    "def f(x): return x + 1",
    'api_key = os.environ["API_KEY"]',
    'token = "${GITHUB_TOKEN}"',
    '"Authorization": "Bearer ${GITHUB_TOKEN}"',
    'password = "changeme"',
    'password = "your-password-here"',
    "SECRET_KEY=<set me>",
    "AZURE_SPEECH_KEY=",
    "AZURE_SPEECH_KEY=${AZURE_SPEECH_KEY}",
    'secret = "aaaaaaaaaaaaaaaaaaaaaaaa"',  # low entropy
    "inputs_hash = '0000000000000000000000000000000000000000000000000000000000000000'",
    "commit 0e44998a1b2c3d4e5f60718293a4b5c6d7e8f901",
    "task-force-readiness-checklist-for-districts",
    "the sk-learn style names like sk-learn are short",
    "-----BEGIN-----",
    '{"type": "FeatureCollection"}',
    "token_count = 1234567890123456",
    "ghp_ is the prefix GitHub uses",
    "Reads STITCH_LLM_PROVIDER (anthropic, openai, fake); keys are never stored.",
]


@pytest.mark.parametrize("rule", sorted(POSITIVE))
def test_p7_each_rule_flags_its_sample(rule: str) -> None:
    rules = {f.rule for f in scan_text(POSITIVE[rule], "x.txt")}
    assert rule in rules, f"{rule} not flagged: {rules}"


@pytest.mark.parametrize(("rule", "sample"), POSITIVE_ALT)
def test_p7_alternate_samples(rule: str, sample: str) -> None:
    assert rule in {f.rule for f in scan_text(sample, "x.txt")}


@pytest.mark.parametrize("sample", CLEAN)
def test_p7_clean_fixtures_not_flagged(sample: str) -> None:
    assert scan_text(sample, "x.txt") == []


def test_p7_env_files() -> None:
    for name in [".env", ".env.production", "config/.env.local", "a\\b\\.env"]:
        assert [f.rule for f in scan_bytes(b"", name)] == ["env-file"], name
    assert scan_bytes(b"A=1\n", ".env.example") == []


def test_allow_marker_skips_only_its_line() -> None:
    text = POSITIVE["github-token"] + "  # secret-scan: allow\n" + POSITIVE["aws-access-key"]
    found = scan_text(text, "x.py")
    assert [f.rule for f in found] == ["aws-access-key"] and found[0].line == 2


def test_findings_are_redacted() -> None:
    f = scan_text(POSITIVE["generic-secret"], "x")[0]
    assert HIGH not in str(f) and str(f).endswith("***")


def test_entropy_helper() -> None:
    assert shannon_entropy("aaaa") == 0
    assert shannon_entropy(HIGH) > 4


def test_binary_and_large_files_are_skipped() -> None:
    assert scan_bytes(b"\x00" + POSITIVE["aws-access-key"].encode(), "x.bin") == []


words = st.text(alphabet="abcdefghijklmnopqrstuvwxyz \n.,", max_size=200)


@given(rule=st.sampled_from(sorted(POSITIVE)), before=words, after=words)
def test_p7_flagged_inside_arbitrary_surroundings(rule: str, before: str, after: str) -> None:
    text = before + "\n" + POSITIVE[rule] + "\n" + after
    assert rule in {f.rule for f in scan_text(text, "x.txt")}


@given(words)
def test_p7_plain_prose_never_flagged(text: str) -> None:
    assert scan_text(text, "x.txt") == []


def test_committed_tree_scans_clean() -> None:
    res = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "secret_scan.py"), "--all"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert res.returncode == 0, res.stderr


# --- staged scan and the guard in a throwaway git repo ---------------------------------------
def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.org")
    git(tmp_path, "config", "user.name", "t")
    return tmp_path


def run_staged_scan(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "secret_scan.py"),
            "--staged",
            "--root",
            str(root),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_staged_scan_reads_the_index(repo: Path) -> None:
    (repo / "a.py").write_text(POSITIVE["aws-access-key"] + "\n", encoding="utf-8")
    git(repo, "add", "a.py")
    (repo / "a.py").write_text("clean = 1\n", encoding="utf-8")  # worktree is clean, index is not
    res = run_staged_scan(repo)
    assert res.returncode == 1 and "aws-access-key" in res.stderr
    git(repo, "add", "a.py")
    assert run_staged_scan(repo).returncode == 0


def test_staged_env_file_is_flagged(repo: Path) -> None:
    (repo / ".env").write_text("A=1\n", encoding="utf-8")
    git(repo, "add", "-f", ".env")
    res = run_staged_scan(repo)
    assert res.returncode == 1 and "env-file" in res.stderr


def test_guard_blocks_only_git_commit_commands(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (repo / "a.txt").write_text(POSITIVE["github-token"] + "\n", encoding="utf-8")
    git(repo, "add", "a.txt")
    import io

    def event(cmd: str) -> io.StringIO:
        return io.StringIO(json.dumps({"tool_name": "shell", "tool_input": {"command": cmd}}))

    monkeypatch.setattr(sys, "stdin", event("git status"))
    assert pre_commit_guard.main(["--root", str(repo)]) == 0
    monkeypatch.setattr(sys, "stdin", event("git commit -m wip"))
    assert pre_commit_guard.main(["--root", str(repo)]) == 2
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json at all"))
    assert pre_commit_guard.main(["--root", str(repo)]) == 0
    assert pre_commit_guard.main(["--git", "--root", str(repo)]) == 2


def test_guard_lints_staged_python(repo: Path) -> None:
    (repo / "bad.py").write_text("import os\nx=1\n", encoding="utf-8")
    git(repo, "add", "bad.py")
    problems = pre_commit_guard.guard(repo)
    assert any("ruff" in p for p in problems)


def test_is_git_commit_detection() -> None:
    yes = ["git commit -m x", "cd x && git commit", "git -C . commit -am y", "git  commit"]
    no = ["git status", "echo git committed", "git log --grep commit", None, ""]
    assert all(hook_io.is_git_commit(c) for c in yes)
    assert not any(hook_io.is_git_commit(c) for c in no)


def test_install_git_hooks_is_idempotent_and_safe(repo: Path) -> None:
    (repo / "scripts" / "hooks").mkdir(parents=True)
    src = (REPO_ROOT / "scripts" / "hooks" / "git-pre-commit").read_bytes()
    (repo / "scripts" / "hooks" / "git-pre-commit").write_bytes(src)
    assert install(repo) == "installed"
    hook = repo / ".git" / "hooks" / "pre-commit"
    assert hook.read_bytes() == src and b"\r\n" not in hook.read_bytes()
    assert src.startswith(b"#!/bin/sh\n")
    assert install(repo) == "unchanged"
    hook.write_text("#!/bin/sh\necho mine\n")
    assert install(repo) == "refused" and "mine" in hook.read_text()
    assert install(repo, force=True) == "installed"
    assert (repo / ".git" / "hooks" / "pre-commit.bak").exists()
