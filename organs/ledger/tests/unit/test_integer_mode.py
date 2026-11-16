"""Integer mode, time limit, gap and status mapping (LED-R1.1, R3.5 to R3.7, R4.3)."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

import pytest

from stitch_ledger.core.optimize import optimize
from stitch_ledger.core.problem import CommoditySpec, DistrictSpec, ProblemSpec
from stitch_ledger.core.solve import RawSolution, SolverError, SolverTimeout


def test_integer_mode_rounds_supply_down_to_whole_units() -> None:
    """Two districts of 10 people, need 1, severity 0.9 and 0.5, supply 5.5 (not a whole number).
    Whole units: at most 5 are sent, all to the more severe district (R_A = 10).
    Objective = w_A * 5/10 = 9 * 0.5 = 4.5."""
    spec = ProblemSpec(
        districts=(DistrictSpec("A", 10, 0.9, 1.0), DistrictSpec("B", 10, 0.5, 1.0)),
        commodities=(CommoditySpec("food", 1.0, 1.0, 5.5),),
        integer=True,
    )
    r = optimize(spec)
    assert r.status == "optimal" and r.solver_name == "SCIP"
    assert r.quantity("A", "food") == 5.0 and r.quantity("B", "food") == 0.0
    assert r.total_coverage == pytest.approx(4.5)


def test_integer_mode_may_send_one_whole_unit_for_a_fractional_need() -> None:
    """Need 0.5 unit (pop 1, 0.5 per person): U = ceil(0.5) = 1, so one unit can be sent and
    coverage stays 1 (design 2.5)."""
    spec = ProblemSpec(
        districts=(DistrictSpec("A", 1, 1.0, 1.0),),
        commodities=(CommoditySpec("food", 0.0, 0.5, 5.0),),
        integer=True,
    )
    r = optimize(spec)
    assert r.quantity("A", "food") == 1.0
    assert r.coverage[0].fraction == 1.0


def hard_spec() -> ProblemSpec:
    import random

    rng = random.Random(7)
    ds = tuple(
        DistrictSpec(f"d{i:03d}", rng.randint(1_000, 90_000), rng.random(), rng.uniform(0.2, 1.0))
        for i in range(200)
    )
    cs = tuple(
        CommoditySpec(f"c{k}", rng.uniform(1, 20), rng.uniform(0.5, 4), 1_500_000.0 * (k + 1))
        for k in range(10)
    )
    return ProblemSpec(
        districts=ds, commodities=cs, budget=9_000_000.0, equity_floor=0.3, integer=True
    )


def test_tiny_time_limit_returns_an_incumbent_with_a_gap_or_times_out() -> None:
    spec = replace(hard_spec(), solver_time_limit_s=0.001)
    try:
        r = optimize(spec)
    except SolverTimeout:
        return
    assert r.status in ("feasible", "optimal")
    if r.status == "feasible":
        assert r.optimality_gap is not None and r.optimality_gap >= 0.0
        assert any("time limit" in w for w in r.warnings)
    else:
        assert r.optimality_gap == 0.0


def raw(status: str, objective: float | None = None, bound: float | None = None) -> RawSolution:
    x = {(0, 0): 3.0} if status in ("optimal", "feasible") else {}
    return RawSolution(status, x, objective, bound, "SCIP", "test", 0.01)  # type: ignore[arg-type]


SMALL = ProblemSpec(
    districts=(DistrictSpec("A", 10, 1.0, 1.0),),
    commodities=(CommoditySpec("food", 1.0, 1.0, 5.0),),
    integer=True,
)


def test_feasible_status_reports_the_relative_gap_from_the_bound() -> None:
    with patch("stitch_ledger.core.optimize.solve", return_value=raw("feasible", 8.0, 10.0)):
        r = optimize(SMALL)
    assert r.status == "feasible"
    assert r.optimality_gap == pytest.approx(0.25)  # (10 - 8) / 8


def test_no_incumbent_at_the_time_limit_raises_timeout() -> None:
    with (
        patch("stitch_ledger.core.optimize.solve", return_value=raw("timeout")),
        pytest.raises(SolverTimeout),
    ):
        optimize(SMALL)


@pytest.mark.parametrize("status", ["error", "infeasible"])
def test_unexpected_solver_status_raises_solver_error(status: str) -> None:
    with (
        patch("stitch_ledger.core.optimize.solve", return_value=raw(status)),
        pytest.raises(SolverError),
    ):
        optimize(SMALL)
