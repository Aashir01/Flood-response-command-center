"""Named regression tests for failures that Hypothesis found (each failed before its fix)."""

from __future__ import annotations

import dataclasses
import itertools
import math

import pytest

from stitch_ledger.core.baseline import proportional_baseline
from stitch_ledger.core.instances import random_spec
from stitch_ledger.core.optimize import optimize
from stitch_ledger.core.problem import CommoditySpec, DistrictSpec, ProblemSpec, normalize
from stitch_ledger.core.tradeoff import sweep


def test_regression_floor_below_solver_tolerance_was_silently_dropped() -> None:
    """Found by LED-P15 (ci profile). Budget 7.1e-4 gives max_feasible_floor ~1e-9. The floor
    was a row ``f >= 1e-9`` that GLOP satisfied within tolerance with f = 0, so the allocation
    was 0 instead of the 1.19e-4 units the floor demands. Fix: the floor is a variable bound on
    x (exact at a simplex bound) in allocation solves."""
    spec = ProblemSpec(
        districts=(DistrictSpec("d03", 396812.0, 0.0, 0.1),),
        commodities=(CommoditySpec("food", 6.0, 3.0, 1190436.0),),
        budget=0.0007142610557970225,
        equity_floor=1.0,
    )
    result = optimize(spec)
    assert result.floor_applied == result.max_feasible_floor < 1e-8
    expected = result.floor_applied * 396812.0 * 0.1 * 3.0
    assert result.quantity("d03", "food") == pytest.approx(expected, rel=1e-6)
    assert result.total_cost <= spec.budget * (1 + 1e-9)  # type: ignore[operator]


def test_regression_subnormal_severity_made_glop_return_abnormal() -> None:
    """Found by LED-P15 (error-policy property). Severity 1.1e-308 gave objective coefficients
    near the subnormal range and GLOP returned ABNORMAL (SolverError). Fix: the objective is
    scaled by its largest coefficient and negligible coefficients are dropped."""
    spec = ProblemSpec(
        districts=(DistrictSpec("d00", 1.0, 1.1125369292536007e-308, 0.0, 1.0),),
        commodities=(CommoditySpec("food", 0.0, 1.0, 1.0),),
        equity_floor=0.5,
        on_infeasible_floor="error",
    )
    result = optimize(spec)
    assert result.status == "optimal"
    assert result.quantity("d00", "food") >= 0.5 * (1 - 1e-9)


def test_regression_tiny_need_made_supply_rhs_huge_and_glop_abnormal() -> None:
    """Found by LED-P12 (ci). Reachable population 1.2e-38 against supply 1: the scaled supply
    row had rhs 8.5e37 and GLOP returned ABNORMAL. Fix: the LP supply limit is capped at the
    total need (the row can never exceed it) so the rhs stays bounded."""
    spec = ProblemSpec(
        districts=(DistrictSpec("d02", 1.0, 0.0, 0.0, 1.175494351e-38),),
        commodities=(CommoditySpec("food", 0.0, 1.0, 1.0),),
    )
    assert optimize(spec).status == "optimal"


def test_regression_budget_repair_wiped_out_free_goods() -> None:
    """Found by LED-P3 (ci). With budget 0, a 1e-83 overshoot from a dropped coefficient was
    repaired by scaling every quantity by 0 / 1e-83 = 0, including the free shelter kits, so
    more supply gave less coverage. Fix: the budget repair only scales items that cost money."""
    spec = ProblemSpec(
        districts=(
            DistrictSpec("d00", 1.0, 0.0, 0.0, 1.1498307467095183e-83),
            DistrictSpec("d02", 1.0, 1.0, 0.1),
        ),
        commodities=(
            CommoditySpec("food", 0.0, 1.0, 0.0),
            CommoditySpec("medical", 1.0, 1.0, 1.0),
            CommoditySpec("shelter", 0.0, 1.0, 2.0),
        ),
        budget=0.0,
    )
    result = optimize(spec)
    assert result.total_coverage == pytest.approx(0.1 / 3)  # shelter covers d02 (w = 0.1)
    assert result.total_cost <= 0.0


def test_regression_glop_presolve_abnormal_on_degenerate_budget_row() -> None:
    """Found by LED-P13 (ci). Budget 8e-4 with unit cost 48: the scaled budget row had rhs 1e-9
    and GLOP's presolve returned ABNORMAL. Fix: LP solves are retried without presolve."""
    spec = ProblemSpec(
        districts=(
            DistrictSpec("d00", 0.0, 0.0, 0.0),
            DistrictSpec("d01", 1.0, 1.0, 0.1),
            DistrictSpec("d02", 16816.0, 0.0, 1.0),
        ),
        commodities=(CommoditySpec("food", 48.0, 1.0, 0.0),),
        budget=0.0008071302404979907,
    )
    result = optimize(spec)
    assert result.status == "optimal" and result.total_coverage == 0.0  # no supply at all


def test_regression_tiny_budget_coverage_is_solver_noise_p13() -> None:
    """Found by LED-P13 (ci profile). Budget 8.6e-4 allows f ~ 1e-9 of one district's need, below
    GLOP's tolerance, so the LP returns coverage 0 while the proportional baseline reports 2.2e-5.
    Relative to the objective scale (sum of weights 21595) that is 1e-9: noise, not a worse plan.
    Resolution: the property tolerance is relative to the objective scale, not to the value."""
    spec = ProblemSpec(
        districts=(
            DistrictSpec("d02", 21595.0, 1.0, 1.0),
            DistrictSpec("d07", 1.0, 0.0, 0.0, 1.0),
        ),
        commodities=(CommoditySpec("food", 10.0, 4.0, 86384.0),),
        budget=0.0008637719451083679,
    )
    problem = normalize(spec)
    result = optimize(spec)
    base = proportional_baseline(problem)
    scale = sum(d.weight for d in problem.districts)
    assert base.total_coverage - result.total_coverage <= 1e-6 * scale
    assert result.total_cost <= spec.budget * (1 + 1e-9)  # type: ignore[operator]


def test_regression_tiny_budget_tradeoff_step_is_solver_noise_p10() -> None:
    """Found by LED-P10 (ci profile). Same mechanism as the P13 case: at floor 0 GLOP returns 0
    coverage for a budget of 8.2e-4, while the floor-1 solve is forced to 8.2e-4 coverage by the
    floor bound. The rise is 1e-9 of the objective scale (818527)."""
    spec = ProblemSpec(
        districts=(
            DistrictSpec("d01", 818527.0, 1.0, 1.0),
            DistrictSpec("d07", 1.0, 0.0, 0.1),
        ),
        commodities=(CommoditySpec("food", 1.0, 1.0, 818528.0),),
        budget=0.0008185260528851874,
    )
    problem = normalize(spec)
    t = sweep(problem, 2, applied_floor=0.0)
    values = [p.total_coverage for p in t.points if p.total_coverage is not None]
    scale = sum(d.weight for d in problem.districts)
    assert all(b <= a + 1e-6 * scale for a, b in itertools.pairwise(values))


def test_regression_scip_varbound_upgrade_returned_zero_plan() -> None:
    """Found by the Ledger eval (seed 0, instance 96). SCIP upgraded ``R f - x <= 0`` with
    R ~ 1.9e7 to varbound constraints and reported an all-zero plan as optimal, while the LP
    relaxation is worth 1.64e6. Fix: ``optimize`` checks the plan against the rounded LP plan and
    re-solves without the varbound upgrade (``formulate.build(no_varbound=True)``)."""
    spec = random_spec(96, 100, 1, equity_floor=0.0, integer=True)
    mip = optimize(spec)
    lp = optimize(dataclasses.replace(spec, integer=False))
    assert mip.status in ("optimal", "feasible")
    assert any("re-solved with safer settings" in w for w in mip.warnings)
    assert mip.total_coverage >= lp.total_coverage * (1 - 1e-3)
    assert mip.total_coverage <= lp.total_coverage * (1 + 1e-9)


def test_regression_integer_budget_repair_kept_the_floor() -> None:
    """Found by the Ledger eval (seed 0, instance 76). Rounding SCIP's solution put the cost over
    the budget by float noise, and the budget repair removed a unit from a district at its
    integer floor (910 < ceil(910.27)). Fix: repairs never go below ``ceil(floor * share)``."""
    spec = random_spec(76, 200, 1, equity_floor=0.5, integer=True)
    result = optimize(spec)
    problem = normalize(spec)
    for i, d in enumerate(problem.districts):
        if i not in problem.active:
            continue
        need_floor = math.ceil(result.floor_applied * problem.share[i][0] - 1e-9)
        assert result.quantity(d.district_id, problem.commodities[0].commodity_id) >= need_floor
    # floors are accepted within 1e-9 of the budget (floors.BUDGET_TOL), so a plan at its floors
    # may exceed the budget by that much and no more
    assert result.total_cost <= spec.budget * (1 + 1e-9)  # type: ignore[operator]


def test_regression_undeliverable_commodity_hid_a_budget_overspend() -> None:
    """Found by LED-P15 (``test_p15_solver_agrees_with_the_closed_form_on_both_sides``, ci
    profile). Budget 0 gives max_feasible_floor 0. The LP at floor 0.001 must be infeasible
    (it has to spend 1e-3 cost units), but GLOP reported it optimal: the budget row was divided
    by the largest raw coefficient, which belonged to ``medical`` (unit cost 25, supply 0, so
    never deliverable), and the 1e-3 overspend became 9.8e-7 on the scaled row, inside the
    solver tolerance. Fix: the budget row is scaled by the largest cost a variable can actually
    add (coefficient times ``min(1, S_k / R_dk)``)."""
    from stitch_ledger.core.floors import max_feasible_floor
    from stitch_ledger.core.formulate import build
    from stitch_ledger.core.solve import solve

    spec = ProblemSpec(
        districts=(DistrictSpec("d00", 68.0, 0.0, 0.1),),
        commodities=(
            CommoditySpec("food", 1.0, 1.0, 1.0),
            CommoditySpec("medical", 25.0, 6.0, 0.0),
        ),
        budget=0.0,
        equity_floor=0.0,
        min_road_access=0.1,
        integer=False,
    )
    problem = normalize(spec)
    assert max_feasible_floor(problem)[0] == 0.0
    assert solve(build(problem, 0.0, integer=False), 10.0).status == "optimal"
    assert solve(build(problem, 0.001, integer=False), 10.0).status == "infeasible"
