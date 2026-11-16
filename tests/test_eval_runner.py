"""BOOT-R7: eval runner skeleton."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from evals import run as runner
from evals.models import ORGANS, Latest, MetricResult, OrganResult, results_schema


def _metric(value: float, target: float | None, direction: str = "higher") -> MetricResult:
    return MetricResult(
        id="demo.metric",
        label="Demo",
        value=value,
        target=target,
        direction=direction,  # type: ignore[arg-type]
        dataset="synthetic",
        timestamp=datetime.now(UTC),
        git_sha="abc1234",
        seed=0,
    )


@pytest.fixture
def results_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(runner, "RESULTS_DIR", tmp_path)
    return tmp_path


def test_committed_schema_matches_models() -> None:
    committed = json.loads((runner.RESULTS_DIR / "schema.json").read_text(encoding="utf-8"))
    assert committed == results_schema()


def test_missing_organ_is_not_run_and_output_validates(
    results_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "git_sha", lambda root=runner.REPO_ROOT: "abc1234")
    assert runner.main(["--organ", "all", "--fast", "--seed", "0"]) == 0
    latest = json.loads((results_dir / "latest.json").read_text(encoding="utf-8"))
    Draft202012Validator(results_schema()).validate(latest)
    assert set(latest["organs"]) == set(ORGANS)
    # organs without an eval module are not_run (the ledger has one since ledger task 14)
    for organ, result in latest["organs"].items():
        if importlib.util.find_spec(f"evals.{organ}") is None:
            assert result["status"] == "not_run", organ
    assert latest["git_sha"] == "abc1234"
    assert (results_dir / "ledger.json").exists()


def test_met_target_direction() -> None:
    assert _metric(0.9, 0.8).met_target is True
    assert _metric(0.7, 0.8).met_target is False
    assert _metric(0.1, 0.2, "lower").met_target is True
    assert _metric(0.3, 0.2, "lower").met_target is False
    assert _metric(1.0, None).met_target is None


def test_run_organ_pass_fail_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import types

    mod = types.ModuleType("evals.ledger")
    mod.__spec__ = importlib_spec("evals.ledger")
    monkeypatch.setitem(sys.modules, "evals.ledger", mod)

    mod.run = lambda fast, seed: [_metric(0.9, 0.8)]  # type: ignore[attr-defined]
    assert runner.run_organ("ledger", True, 0).status == "pass"
    mod.run = lambda fast, seed: [_metric(0.5, 0.8)]  # type: ignore[attr-defined]
    assert runner.run_organ("ledger", True, 0).status == "fail"

    def boom(fast: bool, seed: int) -> list[MetricResult]:
        raise RuntimeError("x")

    mod.run = boom  # type: ignore[attr-defined]
    res = runner.run_organ("ledger", True, 0)
    assert res.status == "error" and "RuntimeError" in res.message


def importlib_spec(name: str):  # type: ignore[no-untyped-def]
    import importlib.machinery

    return importlib.machinery.ModuleSpec(name, None)


def test_merge_latest_uses_existing_files(results_dir: Path) -> None:
    ok = OrganResult(status="pass", metrics=[_metric(0.9, 0.8)])
    (results_dir / "eyes.json").write_text(ok.model_dump_json(), encoding="utf-8")
    latest = runner.merge_latest(results_dir, sha="s")
    assert isinstance(latest, Latest)
    assert latest.organs["eyes"].status == "pass"
    assert latest.organs["voice"].status == "not_run"


def test_unknown_organ_rejected(results_dir: Path) -> None:
    with pytest.raises(SystemExit):
        runner.main(["--organ", "nope"])
