"""Equity trade-off grid, analytic infeasible tail, equity cost and time budget (LED-R10)."""

from __future__ import annotations

import pytest

from stitch_ledger.core.problem import CommoditySpec, DistrictSpec, ProblemSpec, normalize
from stitch_ledger.core.tradeoff import grid, sweep


def instance(budget: float | None = None) -> ProblemSpec:
    """A (pop 100, sev 1) and B (pop 100, sev 0.1), food need 1 at cost 1, supply 100.
    Objective as a function of the floor is 100 - 45 phi (see test_sensitivity)."""
    return ProblemSpec(
        districts=(DistrictSpec("A", 100, 1.0, 1.0), DistrictSpec("B", 100, 0.1, 1.0)),
        commodities=(CommoditySpec("food", 1.0, 1.0, 100.0),),
        budget=budget,
    )


def test_grid_has_steps_points_plus_f_max_sorted_and_unique() -> None:
    assert grid(5, 1.0) == [0.0, 0.25, 0.5, 0.75, 1.0]
    assert grid(3, 0.3) == [0.0, 0.3, 0.5, 1.0]
    assert grid(3, 0.5) == [0.0, 0.5, 1.0]
    assert grid(2, 0.0) == [0.0, 1.0]


def test_curve_matches_the_hand_derived_line() -> None:
    t = sweep(normalize(instance()), 11, applied_floor=0.5)
    assert t.f_max == 1.0 and len(t.points) == 11
    for p in t.points:
        assert p.status == "optimal"
        assert p.total_coverage == pytest.approx(100.0 - 45.0 * p.floor)
    assert t.equity_cost == pytest.approx(22.5)
    assert t.warnings == ()


def test_infeasible_tail_is_analytic_and_uses_no_solves_for_it() -> None:
    """Budget 50 against a full-floor cost of 100 gives f_max = 0.5. Floors 0.6 ... 1.0 are
    reported infeasible with null values without being solved."""
    t = sweep(normalize(instance(budget=50.0)), 11, applied_floor=0.0)
    assert t.f_max == pytest.approx(0.5)
    feasible = [p for p in t.points if p.status != "infeasible"]
    tail = [p for p in t.points if p.status == "infeasible"]
    assert [round(p.floor, 6) for p in feasible] == [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    assert [round(p.floor, 6) for p in tail] == [0.6, 0.7, 0.8, 0.9, 1.0]
    assert all(p.total_coverage is None and p.people_covered is None for p in tail)
    assert t.solves == len(feasible)
    assert t.equity_cost is None


def test_f_max_is_a_point_even_when_off_the_grid() -> None:
    t = sweep(normalize(instance(budget=37.0)), 3, applied_floor=0.0)
    floors = [round(p.floor, 6) for p in t.points]
    assert floors == [0.0, 0.37, 0.5, 1.0]
    assert [p.status for p in t.points] == ["optimal", "optimal", "infeasible", "infeasible"]


def test_equity_cost_is_none_without_a_floor() -> None:
    assert sweep(normalize(instance()), 3, applied_floor=0.0).equity_cost is None


def test_equity_cost_for_an_applied_floor_off_the_grid_costs_an_extra_solve() -> None:
    t = sweep(normalize(instance()), 3, applied_floor=0.2)
    assert t.equity_cost == pytest.approx(9.0)
    assert t.solves == 4  # three grid points plus the applied floor


def test_time_budget_returns_the_points_so_far_and_a_warning() -> None:
    ticks = iter([0.0, 0.1, 0.2, 5.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0])
    t = sweep(
        normalize(instance()), 5, applied_floor=0.75, budget_s=10.0, clock=lambda: next(ticks)
    )
    solved = [p for p in t.points if p.status == "optimal"]
    assert 0 < len(solved) < 5
    assert any("stopped after 10 s" in w for w in t.warnings)
    assert t.equity_cost is None
    assert any("equity_cost" in w for w in t.warnings)


def test_integer_runs_use_the_lp_relaxation() -> None:
    from dataclasses import replace

    t = sweep(normalize(replace(instance(), integer=True)), 3, applied_floor=0.0)
    assert [p.status for p in t.points] == ["optimal"] * 3
    assert t.points[0].total_coverage == pytest.approx(100.0)
