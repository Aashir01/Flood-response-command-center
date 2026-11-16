"""Named regression tests for failures that Hypothesis found (each failed before its fix)."""

from __future__ import annotations

import pytest

from stitch_ledger.core.optimize import optimize
from stitch_ledger.core.problem import CommoditySpec, DistrictSpec, ProblemSpec


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
