"""Duals against hand-derived values (task 3 instances) and finite differences (LED-R6)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from stitch_ledger.core.floors import plan_floor
from stitch_ledger.core.optimize import optimize
from stitch_ledger.core.problem import CommoditySpec, DistrictSpec, ProblemSpec, normalize
from stitch_ledger.core.sensitivity import Sensitivity, analyze


def dist(i: str, pop: float, sev: float, road: float = 1.0, alt: float = 0.0) -> DistrictSpec:
    return DistrictSpec(i, pop, sev, road, alt)


def run(spec: ProblemSpec) -> Sensitivity:
    problem = normalize(spec)
    return analyze(problem, plan_floor(problem).applied)


def price(s: Sensitivity, name: str) -> tuple[float, bool]:
    line = next(p for p in s.shadow_prices if p.constraint == name)
    return line.value, line.binding


def rc(s: Sensitivity, d: str, k: str) -> float:
    return next(r.value for r in s.reduced_costs if (r.district_id, r.commodity_id) == (d, k))


def test_single_commodity_supply_price_is_the_marginal_districts_severity() -> None:
    """Instance 1 of test_lp_hand_solved: A (sev 0.9) full, B (sev 0.5) half, supply 1500.
    One more unit goes to B and is worth s_B * lambda / n = 0.5 (lambda = 1, n = 1), so the
    supply price is 0.5. Reduced cost per unit: A sits at full coverage, so an extra unit of
    capacity at A would be worth 0.9 - 0.5 = 0.4; B is basic (0)."""
    s = run(
        ProblemSpec(
            districts=(dist("A", 1000, 0.9), dist("B", 1000, 0.5)),
            commodities=(CommoditySpec("food", 0.0, 1.0, 1500.0),),
        )
    )
    assert price(s, "supply:food") == (pytest.approx(0.5), True)
    assert rc(s, "A", "food") == pytest.approx(0.4)
    assert rc(s, "B", "food") == pytest.approx(0.0, abs=1e-9)
    assert price(s, "equity_floor") == (0.0, False)
    assert not any(p.constraint.startswith("min_coverage") for p in s.shadow_prices)


def test_budget_price_and_non_binding_supply_with_two_commodities() -> None:
    """Instance 2: budget 1500 is binding, food supply (110 of 150 used) is not, water supply
    equals total need (400) so another unit cannot help. The marginal purchase is B's food:
    value s * lambda / n = 0.5 * 0.5 / 1 = 0.25 per unit at cost 10, so the budget price is
    0.025 coverage-weighted people per currency unit."""
    s = run(
        ProblemSpec(
            districts=(dist("A", 100, 1.0), dist("B", 100, 0.5)),
            commodities=(
                CommoditySpec("food", 10.0, 1.0, 150.0),
                CommoditySpec("water", 1.0, 2.0, 400.0),
            ),
            budget=1500.0,
        )
    )
    assert price(s, "budget") == (pytest.approx(0.025), True)
    assert price(s, "supply:food") == (0.0, False)
    assert price(s, "supply:water")[0] == 0.0


def test_floor_duals_match_the_derivative_of_the_objective_in_phi() -> None:
    """Instance 3: A (sev 1) and B (sev 0.1), supply 100, floor 0.5. Objective as a function of
    the floor is 100 - 45 phi (x_B = 50 phi, so 100 - 50 phi + 5 phi), so d/dphi = -45.
    Per district: f_B sits at its floor with reduced cost 0.1 - 1.0 = -0.9 per unit, times
    R = 100 units per unit of f = -90, and rho = 0.5 turns that into -45 per unit of phi.
    The supply price is A's value, 1.0."""
    s = run(
        ProblemSpec(
            districts=(dist("A", 100, 1.0), dist("B", 100, 0.1)),
            commodities=(CommoditySpec("food", 0.0, 1.0, 100.0),),
            equity_floor=0.5,
        )
    )
    assert price(s, "supply:food") == (pytest.approx(1.0), True)
    assert price(s, "min_coverage:B") == (pytest.approx(-90.0), True)
    assert price(s, "min_coverage:A") == (0.0, False)
    assert price(s, "equity_floor") == (pytest.approx(-45.0), True)


def test_shadow_prices_match_finite_differences() -> None:
    """Re-solve with a small change of each right-hand side (inside one basis) and compare
    the objective change with the reported price."""
    base = ProblemSpec(
        districts=(dist("A", 100, 1.0), dist("B", 100, 0.5), dist("C", 80, 0.2)),
        commodities=(
            CommoditySpec("food", 10.0, 1.0, 150.0),
            CommoditySpec("water", 1.0, 2.0, 300.0),
        ),
        budget=1500.0,
    )
    s = run(base)
    h = 0.01
    for k, c in enumerate(base.commodities):
        bumped = replace(
            base,
            commodities=tuple(
                replace(cc, supply=cc.supply + h) if i == k else cc
                for i, cc in enumerate(base.commodities)
            ),
        )
        delta = optimize(bumped).total_coverage - optimize(base).total_coverage
        assert delta / h == pytest.approx(price(s, f"supply:{c.commodity_id}")[0], abs=1e-6)
    delta = (
        optimize(replace(base, budget=1500.0 + h)).total_coverage - optimize(base).total_coverage
    )
    assert delta / h == pytest.approx(price(s, "budget")[0], abs=1e-6)


def test_integer_run_reports_lp_relaxation_prices() -> None:
    base = ProblemSpec(
        districts=(dist("A", 1000, 0.9), dist("B", 1000, 0.5)),
        commodities=(CommoditySpec("food", 0.0, 1.0, 1500.0),),
        integer=True,
    )
    s = run(base)
    assert price(s, "supply:food")[0] == pytest.approx(0.5)
    assert any("LP relaxation" in n for n in s.notes)


def test_no_reachable_district_gives_zero_prices() -> None:
    s = run(
        ProblemSpec(
            districts=(dist("U", 100, 1.0, road=0.0),),
            commodities=(CommoditySpec("food", 1.0, 1.0, 50.0),),
            budget=10.0,
        )
    )
    assert price(s, "supply:food")[0] == 0.0
    assert price(s, "budget")[0] == 0.0
    assert s.reduced_costs == ()
