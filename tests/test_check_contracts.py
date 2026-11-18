"""BOOT-P5 and BOOT-R3: contract checker behaviour."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest
from check_contracts import REPO_ROOT, run_checks
from hypothesis import given, settings
from hypothesis import strategies as st

from stitch_common import CONTRACT_VERSION
from stitch_common.schemas import all_schemas

SCRIPT = REPO_ROOT / "scripts" / "check_contracts.py"
SCHEMAS = all_schemas()


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


def make_root(dest: Path) -> Path:
    """Minimal repo copy holding only what the checker reads."""
    common = dest / "packages" / "stitch_common"
    shutil.copytree(REPO_ROOT / "packages" / "stitch_common" / "schemas", common / "schemas")
    shutil.copy2(REPO_ROOT / "packages" / "stitch_common" / "contracts.lock.json", common)
    md = dest / ".kiro" / "steering"
    md.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / ".kiro" / "steering" / "mcp-contracts.md", md)
    return dest


def test_p5_committed_tree_passes() -> None:
    res = run_script()
    assert res.returncode == 0, res.stderr
    assert "ok" in res.stdout


def test_p5_schema_edit_without_lock_update_fails(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    target = root / "packages/stitch_common/schemas/ledger.optimize_allocation.in.json"
    schema = json.loads(target.read_text(encoding="utf-8"))
    schema["properties"]["integer"]["default"] = False
    target.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    res = run_script("--root", str(root))
    assert res.returncode == 1
    assert "ledger.optimize_allocation.in.json" in res.stderr
    assert "committed/" in res.stderr and "generated/" in res.stderr  # unified diff present


def test_lock_hash_mismatch_fails(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    lock_path = root / "packages/stitch_common/contracts.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["schemas"]["common.interval.json"] = "0" * 64
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    res = run_script("--root", str(root))
    assert res.returncode == 1 and "common.interval.json" in res.stderr


def test_schema_added_and_removed_are_reported(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    schemas = root / "packages/stitch_common/schemas"
    (schemas / "common.interval.json").unlink()
    (schemas / "zzz.extra.json").write_text("{}", encoding="utf-8")
    res = run_script("--root", str(root))
    assert res.returncode == 1
    assert "missing on disk: common.interval.json" in res.stderr
    assert "stale schema file" in res.stderr and "zzz.extra.json" in res.stderr


def test_version_mismatch_with_markdown_fails(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    md = root / ".kiro/steering/mcp-contracts.md"
    md.write_text(
        md.read_text(encoding="utf-8").replace(
            f"# MCP contracts (v{CONTRACT_VERSION})", "# MCP contracts (v9.9)"
        ),
        encoding="utf-8",
    )
    res = run_script("--root", str(root))
    assert res.returncode == 1 and "9.9" in res.stderr


def test_missing_change_log_entry_fails(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    md = root / ".kiro/steering/mcp-contracts.md"
    lines = [
        ln
        for ln in md.read_text(encoding="utf-8").splitlines()
        if not ln.startswith(f"- {CONTRACT_VERSION}")
    ]
    md.write_text("\n".join(lines), encoding="utf-8")
    res = run_script("--root", str(root))
    assert res.returncode == 1 and "change log" in res.stderr


def test_update_repairs_a_stale_tree(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    (root / "packages/stitch_common/schemas/common.interval.json").write_text(
        "{}", encoding="utf-8"
    )
    assert run_script("--root", str(root)).returncode == 1
    assert run_script("--root", str(root), "--update").returncode == 0
    assert run_script("--root", str(root)).returncode == 0


def test_update_refuses_when_markdown_is_wrong(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    md = root / ".kiro/steering/mcp-contracts.md"
    md.write_text(
        md.read_text(encoding="utf-8").replace(f"(v{CONTRACT_VERSION})", "(v9.9)"),
        encoding="utf-8",
    )
    assert run_script("--root", str(root), "--update").returncode == 1


def write_organ(root: Path, organ: str, tool_schemas: str) -> None:
    pkg = root / "organs" / organ / "src" / f"stitch_{organ}"
    pkg.mkdir(parents=True)
    (root / "organs" / organ / "pyproject.toml").write_text("[project]\nname='x'\n")
    (pkg / "__init__.py").write_text("")
    (pkg / "models.py").write_text(f"TOOL_SCHEMAS = {tool_schemas}\n")


def test_organ_schema_drift_is_detected(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write_organ(root, "ledger", '{"optimize_allocation": {"type": "object"}, "bogus": {}}')
    res = run_script("--root", str(root))
    assert res.returncode == 1
    assert "sensitivity_report is in the contract but not in TOOL_SCHEMAS" in res.stderr
    assert "bogus is not in the contract" in res.stderr
    assert "input schema of optimize_allocation differs" in res.stderr


def test_organ_that_uses_the_common_models_passes(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write_organ(
        root,
        "voice",
        "{n: s.input.model_json_schema(mode='validation') "
        "for n, s in __import__('stitch_common.organs', fromlist=['x'])"
        ".ORGAN_TOOLS['voice'].items()}",
    )
    res = run_script("--root", str(root))
    assert res.returncode == 0, res.stderr


def _mutate(schema: dict[str, Any], how: int) -> dict[str, Any]:
    s = copy.deepcopy(schema)
    if how == 0:
        s.setdefault("properties", {})["__added__"] = {"type": "string"}
    elif how == 1:
        s["title"] = str(s.get("title", "")) + "X"
    else:
        s["description"] = "changed"
    return s


@settings(deadline=None)
@given(name=st.sampled_from(sorted(SCHEMAS)), how=st.integers(0, 2))
def test_p5_any_schema_change_is_caught_and_update_accepts_it(name: str, how: int) -> None:
    mutated = {**SCHEMAS, name: _mutate(SCHEMAS[name], how)}
    with tempfile.TemporaryDirectory() as td:
        root = make_root(Path(td) / "r")
        problems = run_checks(root, CONTRACT_VERSION, mutated)
        assert problems and any(name in p for p in problems)
        assert run_checks(root, CONTRACT_VERSION, mutated, update=True) == []
        assert run_checks(root, CONTRACT_VERSION, mutated) == []


# Versions with no change-log entry (0.5 stopped qualifying when the contract reached v0.5).
@pytest.mark.parametrize("version", ["0.9", "1.0"])
def test_in_process_version_mismatch(version: str, tmp_path: Path) -> None:
    root = make_root(tmp_path)
    problems = run_checks(root, version, SCHEMAS)
    assert any("heading version" in p for p in problems)
    assert any("change log" in p for p in problems)
