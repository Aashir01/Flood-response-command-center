"""BOOT-R8: the CI workflow parses and carries the required steps."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

CI = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"


def _run_text() -> str:
    doc: dict[str, Any] = yaml.safe_load(CI.read_text(encoding="utf-8"))
    steps = doc["jobs"]["python"]["steps"]
    return "\n".join(str(s.get("run", "")) + str(s.get("uses", "")) for s in steps)


def test_ci_parses_and_has_required_steps() -> None:
    doc = yaml.safe_load(CI.read_text(encoding="utf-8"))
    assert (
        doc[True]["pull_request"] is None or "pull_request" in doc[True]
    )  # YAML 1.1: `on` is True
    text = _run_text()
    for needle in (
        "setup-uv",
        "uv sync --all-packages --frozen",
        "ruff check",
        "ruff format --check",
        "mypy",
        "pytest",
        "--hypothesis-profile=ci",
        "scripts/check_contracts.py",
        "scripts/secret_scan.py --all",
        "gitleaks",
        "git check-ignore -q .kiro",
        "git ls-files .kiro",
    ):
        assert needle in text, needle


def test_ci_does_not_run_live_tests() -> None:
    assert "not live" in _run_text()
