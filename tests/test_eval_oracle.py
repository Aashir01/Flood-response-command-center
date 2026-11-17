"""Oracle eval smoke (task 11; ORA-R7, ORA-P7 eval, ORA-P8): the fast run is deterministic, every
record carries ``target_kind = modeled_glofas``, metrics fit the dashboard schema, and the report
states that no observed gauge validation was performed."""

from __future__ import annotations

from typing import Any

import pytest

from evals.models import MetricResult
from evals.oracle import TARGET_KIND, TARGET_LABEL, evaluate, to_metrics


@pytest.fixture(scope="module")
def report() -> dict[str, Any]:
    return evaluate(fast=True, seed=0)


def test_report_labels_and_protocol(report: dict[str, Any]) -> None:
    assert report["target_kind"] == TARGET_KIND and report["target_label"] == TARGET_LABEL
    assert report["observed_validation"] == "not performed"
    assert {r["target_kind"] for r in report["by_lead"]} == {TARGET_KIND}
    assert {r["target_kind"] for r in report["by_station_lead"]} == {TARGET_KIND}
    assert {r["split"] for r in report["by_lead"]} == {"test", "stress_2022"}
    leads = sorted(r["lead"] for r in report["by_lead"] if r["split"] == "test")
    assert leads == list(range(1, 15))
    for name in ("model", "persistence", "persistence_prob", "climatology"):
        assert report["overall"]["test"][name]["crps"] > 0


def test_metrics_fit_dashboard_schema(report: dict[str, Any]) -> None:
    metrics = to_metrics(report, seed=0)
    ids = [m.id for m in metrics]
    assert len(ids) == len(set(ids))
    for m in metrics:
        MetricResult.model_validate(m.model_dump())
        assert m.notes.startswith(f"target_kind={TARGET_KIND}")
        assert m.mode == "demo" and m.seed == 0
    assert "oracle.coverage.c80.test" in ids and "oracle.coverage.c80.stress2022" in ids
    assert "oracle.check.ora_p7" in ids


def test_fast_run_is_deterministic(report: dict[str, Any]) -> None:
    assert evaluate(fast=True, seed=0) == report
