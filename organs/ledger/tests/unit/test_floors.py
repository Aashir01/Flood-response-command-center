"""Floor policy: hand-solved cases and reason text (LED-R3.2 to LED-R3.4)."""

from __future__ import annotations

import pytest

from stitch_ledger.core.floors import max_feasible_floor, plan_floor
from stitch_ledger.core.optimize import optimize
from stitch_ledger.core.problem import CommoditySpec, DistrictSpec, ProblemSpec, normalize


def two_districts(**kw: object) -> ProblemSpec:
    return ProblemSpec(
        districts=(DistrictSpec("A", 100, 1.0, 1.0), DistrictSpec("B", 100, 0.1, 1.0)),
        commodities=(CommoditySpec("food", 10.0, 1.0, 100.0),),
        **kw,  # type: ignore[arg-type]
    )


def test_lp_max_feasible_floor_is_budget_over_full_floor_cost() -> None:
    """Supply 100 of need 200 gives rho 0.5 and share 50 each. Delivering the full proportional
    share costs 10 * (50 + 50) = 1000. With budget 500 the floor can be at most 500/1000 = 0.5.
    Without a budget, or with a budget of at least 1000, the floor can be 1."""
    assert max_feasible_floor(normalize(two_districts(budget=500.0))) == (0.5, "budget")
    assert max_feasible_floor(normalize(two_districts())) == (1.0, None)
    assert max_feasible_floor(normalize(two_districts(budget=1000.0))) == (1.0, None)
    assert max_feasible_floor(normalize(two_districts(budget=0.0))) == (0.0, "budget")


def test_relax_policy_applies_the_highest_feasible_floor_and_warns() -> None:
    spec = two_districts(budget=500.0, equity_floor=0.8)
    plan = plan_floor(normalize(spec))
    assert (plan.requested, plan.max_feasible, plan.applied) == (0.8, 0.5, 0.5)
    assert not plan.infeasible and plan.warning is not None and "0.5" in plan.warning
    result = optimize(spec)
    assert result.status == "optimal"
    assert (result.floor_requested, result.floor_applied) == (0.8, 0.5)
    assert result.max_feasible_floor == 0.5
    assert any("max_feasible_floor 0.5" in w for w in result.warnings)
    # Budget 500 buys 50 units; the floor needs 25 each (0.5 * 50), so 50 are spent on the floor.
    assert result.quantity("A", "food") == pytest.approx(25.0)
    assert result.quantity("B", "food") == pytest.approx(25.0)
    assert result.total_cost == pytest.approx(500.0)


def test_error_policy_reports_infeasible_with_the_binding_constraint() -> None:
    spec = two_districts(budget=500.0, equity_floor=0.8, on_infeasible_floor="error")
    result = optimize(spec)
    assert result.status == "infeasible"
    assert result.infeasibility_reason is not None
    assert "budget" in result.infeasibility_reason
    assert "0.5" in result.infeasibility_reason and "0.8" in result.infeasibility_reason
    assert all(q == 0.0 for _, _, q in result.allocation) and result.total_coverage == 0.0
    assert result.floor_requested == 0.8 and result.max_feasible_floor == 0.5


def test_a_feasible_floor_is_applied_as_requested_under_both_policies() -> None:
    for policy in ("relax", "error"):
        spec = two_districts(budget=500.0, equity_floor=0.5, on_infeasible_floor=policy)
        result = optimize(spec)
        assert result.status == "optimal" and result.floor_applied == 0.5
        assert not result.warnings or all("max_feasible_floor" not in w for w in result.warnings)


def test_integer_max_feasible_floor_by_bisection_is_limited_by_supply() -> None:
    """Three districts of 100 people, need 1, supply 100: rho = 1/3, share = 33.33 each.
    The integer floor is ceil(phi * 33.33). Three units per 33 need phi <= 33/33.33 = 0.99
    (3 * 33 = 99 <= 100); at phi just above 0.99 each needs 34 and 102 > 100."""
    spec = ProblemSpec(
        districts=tuple(DistrictSpec(i, 100, 0.5, 1.0) for i in "abc"),
        commodities=(CommoditySpec("food", 1.0, 1.0, 100.0),),
        integer=True,
    )
    value, limiting = max_feasible_floor(normalize(spec))
    assert value == pytest.approx(0.99, abs=1e-9)
    assert limiting == "supply:food"


def test_integer_floor_limited_by_budget() -> None:
    """One district of 100 people, need 1, supply 1000, unit cost 10, so share = 100 and the full
    floor costs 1000. With budget 300 the floor is at most 300 / 1000 = 0.3 (30 units, cost 300)."""
    spec = ProblemSpec(
        districts=(DistrictSpec("a", 100, 0.5, 1.0),),
        commodities=(CommoditySpec("food", 10.0, 1.0, 1000.0),),
        budget=300.0,
        integer=True,
    )
    value, limiting = max_feasible_floor(normalize(spec))
    assert value == pytest.approx(0.3, abs=1e-9)
    assert limiting == "budget"
