"""DEP-R3.1, R3.3, R5.2, R8.1-R8.3, DEP-P2, DEP-P3: repo hygiene checks on temporary git repos."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "bin" / "check_repo_hygiene.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_repo_hygiene", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_repo_hygiene"] = mod
    spec.loader.exec_module(mod)
    return mod


hy = _load()


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.invalid")
    _git(tmp_path, "config", "user.name", "t")
    _write(tmp_path, "LICENSE", "MIT License\n\nCopyright (c) Stitch\n")
    for f in ("README.md", "THIRD_PARTY.md", "docs/kiro-writeup.md", "deploy/README.md"):
        _write(tmp_path, f, "# x\n")
    for part in hy.KIRO_PARTS:
        _write(tmp_path, f".kiro/{part}/x.md", "x\n")
    _write(
        tmp_path,
        ".kiro/settings/mcp.json",
        json.dumps(
            {"mcpServers": {"gh": {"headers": {"Authorization": "Bearer ${GITHUB_TOKEN}"}}}}
        ),
    )
    _write(tmp_path, ".gitignore", "__pycache__/\n.env\n")
    _write(tmp_path, "data/demo/MANIFEST.md", "| `ledger/a.parquet` | CC BY 4.0 |\n")
    _write(tmp_path, "data/demo/ledger/a.parquet", "x")
    _git(tmp_path, "add", "-A")
    return tmp_path


def _fails(root: Path) -> list[str]:
    failures, _ = hy.run(root, third_party="off")
    return failures


def test_clean_repo_passes(repo: Path) -> None:
    assert _fails(repo) == []


def test_gitignored_kiro_fails(repo: Path) -> None:
    _write(repo, ".gitignore", "__pycache__/\n.kiro/\n")
    _git(repo, "add", ".gitignore")
    fails = _fails(repo)
    assert any("would ignore .kiro" in f for f in fails), fails
    assert any("check-ignore" in f for f in fails), fails


def test_untracked_kiro_fails(repo: Path) -> None:
    _git(repo, "rm", "-r", "-q", "--cached", ".kiro")
    assert any("no tracked files under .kiro" in f for f in _fails(repo))


def test_tracked_env_file_fails(repo: Path) -> None:
    _write(repo, "deploy/env/.env", "X=1\n")
    _git(repo, "add", "-f", "deploy/env/.env")
    assert any("deploy/env/.env is tracked" in f for f in _fails(repo))


def test_env_example_is_allowed(repo: Path) -> None:
    _write(repo, "deploy/env/.env.example", "ANTHROPIC_API_KEY=\n")
    _git(repo, "add", "-f", "deploy/env/.env.example")
    assert _fails(repo) == []


def test_credential_in_mcp_json_fails(repo: Path) -> None:
    token = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4"  # secret-scan: allow (test fixture)
    doc = {"mcpServers": {"gh": {"env": {"GITHUB_TOKEN": token}}}}
    _write(repo, ".kiro/settings/mcp.json", json.dumps(doc))
    assert any("mcp.json" in f for f in _fails(repo))


def test_literal_password_in_mcp_json_fails(repo: Path) -> None:
    doc = {"mcpServers": {"db": {"env": {"DB_PASSWORD": "hunter2hunter2"}}}}
    _write(repo, ".kiro/settings/mcp.json", json.dumps(doc))
    assert any("literal secret-like value" in f for f in _fails(repo))


def test_unlisted_demo_file_fails(repo: Path) -> None:
    _write(repo, "data/demo/ledger/b.parquet", "x")
    _git(repo, "add", "data/demo/ledger/b.parquet")
    assert any("data/demo/ledger/b.parquet" in f for f in _fails(repo))


def test_glob_manifest_row_covers_files(repo: Path) -> None:
    _write(repo, "data/demo/MANIFEST.md", "| `ledger/a.parquet` |\n| recorded/library/** | x |\n")
    _write(repo, "data/demo/recorded/library/q/a.json", "{}")
    _git(repo, "add", "-A")
    assert _fails(repo) == []


def test_missing_required_file_fails(repo: Path) -> None:
    (repo / "deploy" / "README.md").unlink()
    assert any("deploy/README.md is missing" in f for f in _fails(repo))


def test_third_party_strict_and_allow_list(repo: Path) -> None:
    _write(repo, "pkg/pyproject.toml", '[project]\nname="x"\ndependencies=["leftpad>=1"]\n')
    _git(repo, "add", "pkg/pyproject.toml")
    failures, _ = hy.run(repo, third_party="strict")
    assert any("leftpad" in f for f in failures)
    _, advisories = hy.run(repo, third_party="advisory")
    assert any("leftpad" in a for a in advisories)
    _write(repo, "deploy/third_party_allow.txt", "leftpad  # test only\n")
    failures, _ = hy.run(repo, third_party="strict")
    assert failures == []
