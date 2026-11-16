"""LED-R9: the Ledger eval is seeded and reproducible (except wall times) and meets its targets."""

from __future__ import annotations

import itertools

from evals import ledger
from evals.models import MetricResult

TIMING = ("ledger.lp_solve_time_p95_s", "ledger.mip_solve_time_p95_s", "ledger.solve_time_max_s")


def _values(metrics: list[MetricResult]) -> dict[str, float]:
    return {m.id: m.value for m in metrics if m.id not in TIMING}


def test_fast_eval_is_reproducible_and_passes() -> None:
    a = ledger.run(fast=True, seed=0, write_details=False)
    b = ledger.run(fast=True, seed=0, write_details=False)
    assert _values(a) == _values(b)
    ids = [m.id for m in a]
    assert len(ids) == len(set(ids))
    assert all(m.met_target is not False for m in a), [m.id for m in a if m.met_target is False]
    by_id = {m.id: m for m in a}
    assert by_id["ledger.feasibility_rate"].value == 1.0
    assert by_id["ledger.demo.equity_curve.floor_0.0"].value == 1.0
    assert by_id["ledger.demo.equity_curve.floor_0.0"].mode == "demo"
    assert by_id["ledger.feasibility_rate"].mode == "synthetic"


def test_other_seed_changes_the_instances() -> None:
    a = _values(ledger.run(fast=True, seed=0, write_details=False))
    b = _values(ledger.run(fast=True, seed=1, write_details=False))
    assert a["ledger.coverage_uplift_mean"] != b["ledger.coverage_uplift_mean"]


def test_equity_curve_is_non_increasing() -> None:
    curve = [p for p in ledger.demo_curve() if p["total_coverage"] is not None]
    values = [float(p["total_coverage"]) for p in curve]  # type: ignore[arg-type]
    assert all(b <= a * (1 + 1e-9) for a, b in itertools.pairwise(values))
