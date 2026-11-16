"""BOOT-P6 and BOOT-R5: the scaffold script, in throwaway copies of the repo only."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from scaffold_organ import REPO_ROOT, ScaffoldError, plan, scaffold

from stitch_common.organs import ORGAN_TOOLS

SCRIPT = REPO_ROOT / "scripts" / "scaffold_organ.py"
ORGANS = sorted(ORGAN_TOOLS)

MCP_JSON = {
    "mcpServers": {
        **{
            f"{o}-mcp": {
                "command": "uv",
                "args": ["run", "--package", f"stitch-{o}", "python", "-m", f"stitch_{o}.server"],
                "env": {"STITCH_MODE": "demo"},
                "disabled": True,
            }
            for o in ORGANS
        },
        "fetch": {"command": "uvx", "args": ["mcp-server-fetch"], "disabled": False},
    }
}


def make_repo(dest: Path) -> Path:
    """Minimal repo copy: what the scaffold and check_contracts read or edit."""
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("pyproject.toml", "THIRD_PARTY.md"):
        shutil.copy2(REPO_ROOT / name, dest / name)
    shutil.copytree(REPO_ROOT / ".kiro" / "templates", dest / ".kiro" / "templates")
    steering = dest / ".kiro" / "steering"
    steering.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / ".kiro" / "steering" / "mcp-contracts.md", steering)
    common = dest / "packages" / "stitch_common"
    common.mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "packages" / "stitch_common" / "schemas", common / "schemas")
    shutil.copy2(REPO_ROOT / "packages" / "stitch_common" / "contracts.lock.json", common)
    settings_dir = dest / ".kiro" / "settings"
    settings_dir.mkdir(parents=True)
    (settings_dir / "mcp.json").write_text(json.dumps(MCP_JSON, indent=2) + "\n", encoding="utf-8")
    return dest


def tree_hash(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and ".git" not in p.parts:
            out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def run(
    *args: str, cwd: Path, env_extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, **(env_extra or {})}
    return subprocess.run(
        list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=600,
        check=False,
    )


def py(
    *args: str, cwd: Path, env_extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return run(sys.executable, *args, cwd=cwd, env_extra=env_extra)


def scaffold_cli(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return py(str(SCRIPT), "--root", str(root), *args, cwd=root)


def test_generated_organ_passes_its_own_tests_and_contract_check(tmp_path: Path) -> None:
    """P6 setup + BOOT-R5.5: scaffold ledger into a temp copy, run its tests and check_contracts."""
    real_before = tree_hash(REPO_ROOT / "organs")
    pyproject_before = (REPO_ROOT / "pyproject.toml").read_bytes()
    third_before = (REPO_ROOT / "THIRD_PARTY.md").read_bytes()

    root = make_repo(tmp_path / "repo")
    res = scaffold_cli(
        root,
        "--organ",
        "ledger",
        "--package",
        "stitch_ledger",
        "--tools",
        "optimize_allocation,sensitivity_report",
    )
    assert res.returncode == 0, res.stderr + res.stdout

    src = root / "organs" / "ledger" / "src"
    for rel in [
        "organs/ledger/pyproject.toml",
        "organs/ledger/README.md",
        "organs/ledger/src/stitch_ledger/server.py",
        "organs/ledger/src/stitch_ledger/models.py",
        "organs/ledger/src/stitch_ledger/core/optimize_allocation.py",
        "organs/ledger/src/stitch_ledger/core/sensitivity_report.py",
        "organs/ledger/tests/test_smoke_stdio.py",
        "organs/ledger/tests/contract/test_contract.py",
        "organs/ledger/tests/property/test_envelope.py",
        "organs/ledger/tests/unit/test_core.py",
        ".kiro/specs/ledger-mcp/requirements.md",
        ".kiro/specs/ledger-mcp/design.md",
        ".kiro/specs/ledger-mcp/tasks.md",
    ]:
        assert (root / rel).is_file(), rel

    env = {"PYTHONPATH": str(src), "STITCH_MODE": "demo"}
    tests = py(
        "-m", "pytest", "organs/ledger", "-q", "-p", "no:cacheprovider", cwd=root, env_extra=env
    )
    assert tests.returncode == 0, tests.stdout + tests.stderr
    assert "passed" in tests.stdout

    contracts = py(str(REPO_ROOT / "scripts" / "check_contracts.py"), "--root", str(root), cwd=root)
    assert contracts.returncode == 0, contracts.stderr

    lint = py("-m", "ruff", "check", "organs", cwd=root)
    assert lint.returncode == 0, lint.stdout
    fmt = py("-m", "ruff", "format", "--check", "organs", cwd=root)
    assert fmt.returncode == 0, fmt.stdout
    types = py("-m", "mypy", "organs/ledger/src", cwd=root, env_extra={"MYPYPATH": str(src)})
    assert types.returncode == 0, types.stdout + types.stderr

    # The real repository was not touched.
    assert tree_hash(REPO_ROOT / "organs") == real_before
    assert (REPO_ROOT / "pyproject.toml").read_bytes() == pyproject_before
    assert (REPO_ROOT / "THIRD_PARTY.md").read_bytes() == third_before
    assert not (REPO_ROOT / "organs" / "ledger" / "src").exists()


def test_side_edits_are_applied(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    assert '"organs/voice",' in (root / "pyproject.toml").read_text(encoding="utf-8")
    scaffold(root, "voice")
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert '"organs/voice"' not in pyproject and '"organs/ledger",' in pyproject
    third = (root / "THIRD_PARTY.md").read_text(encoding="utf-8")
    assert third.count("## voice-mcp code libraries") == 1
    mcp = json.loads((root / ".kiro/settings/mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["voice-mcp"]["disabled"] is False
    assert mcp["mcpServers"]["ledger-mcp"]["disabled"] is True
    assert mcp["mcpServers"]["fetch"]["disabled"] is False


def test_mcp_entry_is_added_when_missing(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    (root / ".kiro/settings/mcp.json").write_text('{"mcpServers": {}}', encoding="utf-8")
    scaffold(root, "eyes")
    entry = json.loads((root / ".kiro/settings/mcp.json").read_text(encoding="utf-8"))[
        "mcpServers"
    ]["eyes-mcp"]
    assert entry["disabled"] is False and entry["command"] == "uv"
    assert entry["args"][-2:] == ["stitch_eyes.server", "--stdio"]


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    before = tree_hash(root)
    res = scaffold_cli(root, "--organ", "oracle", "--dry-run")
    assert res.returncode == 0
    assert "would create" in res.stdout and "organs/oracle/pyproject.toml" in res.stdout
    assert tree_hash(root) == before


def test_existing_files_are_not_overwritten_without_force(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    scaffold(root, "eyes")
    server = root / "organs/eyes/src/stitch_eyes/server.py"
    core = root / "organs/eyes/src/stitch_eyes/core/segment_flood.py"
    core.write_text("# my implementation\n", encoding="utf-8")
    spec = root / ".kiro/specs/eyes-mcp/requirements.md"
    spec.write_text("# approved\n", encoding="utf-8")
    server.unlink()

    actions = scaffold(root, "eyes")
    kinds = {a.path: a.kind for a in actions}
    assert kinds["organs/eyes/src/stitch_eyes/core/segment_flood.py"] == "skip"
    assert kinds["organs/eyes/src/stitch_eyes/server.py"] == "create"
    assert core.read_text(encoding="utf-8") == "# my implementation\n"

    scaffold(root, "eyes", force=True)
    assert "NotImplementedError" in core.read_text(encoding="utf-8")  # overwritten by --force
    assert spec.read_text(encoding="utf-8") == "# approved\n"  # specs are never overwritten


@pytest.mark.parametrize(
    "args",
    [
        ["--organ", "nope"],
        ["--organ", "ledger", "--tools", "optimize_allocation"],
        ["--organ", "ledger", "--tools", "optimize_allocation,bogus"],
        ["--organ", "ledger", "--package", "other_pkg"],
    ],
)
def test_invalid_arguments_exit_2_and_write_nothing(tmp_path: Path, args: list[str]) -> None:
    root = make_repo(tmp_path)
    before = tree_hash(root)
    res = scaffold_cli(root, *args)
    assert res.returncode == 2 and "scaffold_organ:" in res.stderr
    assert tree_hash(root) == before


def test_plan_rejects_unknown_organ() -> None:
    with pytest.raises(ScaffoldError):
        plan(REPO_ROOT, "../../etc")


@settings(deadline=None, max_examples=15)
@given(organ=st.sampled_from(ORGANS))
def test_p6_second_run_changes_nothing(organ: str) -> None:
    with tempfile.TemporaryDirectory() as td:
        root = make_repo(Path(td) / "repo")
        first = scaffold(root, organ)
        assert any(a.kind == "create" for a in first)
        after_first = tree_hash(root)
        second = scaffold(root, organ)
        assert tree_hash(root) == after_first
        assert not any(a.kind in ("create", "overwrite", "edit") for a in second)


def test_scaffold_output_is_deterministic(tmp_path: Path) -> None:
    a = make_repo(tmp_path / "a")
    b = make_repo(tmp_path / "b")
    for organ in ORGANS:
        scaffold(a, organ)
        scaffold(b, organ)
    assert tree_hash(a) == tree_hash(b)


def test_all_five_organs_scaffold_compile_and_pass_check_contracts(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    for organ in ORGANS:
        scaffold(root, organ)
    compiled = py("-m", "compileall", "-q", "organs", cwd=root)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    res = py(str(REPO_ROOT / "scripts" / "check_contracts.py"), "--root", str(root), cwd=root)
    assert res.returncode == 0, res.stderr
    lint = py("-m", "ruff", "check", "organs", cwd=root)
    assert lint.returncode == 0, lint.stdout
    assert (
        '"organs/'
        not in (root / "pyproject.toml")
        .read_text(encoding="utf-8")
        .split("exclude = [")[1]
        .split("]")[0]
    )
