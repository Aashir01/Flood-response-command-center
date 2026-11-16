"""Hand-solved LP instances (task 3). Each docstring carries the derivation."""

from __future__ import annotations

import pytest

from stitch_ledger.core.optimize import optimize
from stitch_ledger.core.problem import CommoditySpec, DistrictSpec, ProblemSpec


def dist(i: str, pop: float, sev: float, road: float = 1.0, alt: float = 0.0) -> DistrictSpec:
    return DistrictSpec(i, pop, sev, road, alt)


def test_single_commodity_goes_to_the_most_severe_district_first() -> None:
    """A (pop 1000, severity 0.9) and B (pop 1000, severity 0.5), one commodity with need 1 per
    person, supply 1500, no budget, no floor.

    The value of one unit at d is severity_d (population cancels), so A is filled first:
    x_A = 1000 (coverage 1), x_B = 500 (coverage 0.5).
    Objective = w_A * 1 + w_B * 0.5 with w_A = 900, w_B = 500: 900 + 250 = 1150.
    People covered = 1000 + 500 = 1500, cost 0.
    """
    spec = ProblemSpec(
        districts=(dist("A", 1000, 0.9), dist("B", 1000, 0.5)),
        commodities=(CommoditySpec("food", 0.0, 1.0, 1500.0),),
    )
    r = optimize(spec)
    assert r.status == "optimal" and r.optimality_gap == 0.0
    assert r.quantity("A", "food") == pytest.approx(1000.0)
    assert r.quantity("B", "food") == pytest.approx(500.0)
    assert r.total_coverage == pytest.approx(1150.0)
    assert r.people_covered == pytest.approx(1500.0)
    assert r.cost_per_person_covered == 0.0


def test_two_commodities_with_a_budget_buy_the_cheapest_coverage_first() -> None:
    """A (pop 100, severity 1) and B (pop 100, severity 0.5). Food: cost 10, need 1, supply 150.
    Water: cost 1, need 2, supply 400. lambda = 1/2 each. Budget 1500.

    R_food = 100 each, R_water = 200 each; w_A = 100, w_B = 50.
    Value of a unit is s_d * lambda / n_k: food A 0.5, B 0.25; water A 0.25, B 0.125.
    Value per currency: food A 0.05, B 0.025; water A 0.25, B 0.125.
    All water (cost 400, within supply 400) is bought first. Left: 1100 for food. A food (100
    units, cost 1000) next, then B food with the last 100 currency: 10 units.
    cov_A = 0.5 * 1 + 0.5 * 1 = 1; cov_B = 0.5 * 0.1 + 0.5 * 1 = 0.55.
    Objective = 100 * 1 + 50 * 0.55 = 127.5, cost = 1500, people = 100 + 55 = 155.
    """
    spec = ProblemSpec(
        districts=(dist("A", 100, 1.0), dist("B", 100, 0.5)),
        commodities=(
            CommoditySpec("food", 10.0, 1.0, 150.0),
            CommoditySpec("water", 1.0, 2.0, 400.0),
        ),
        budget=1500.0,
    )
    r = optimize(spec)
    assert r.status == "optimal"
    assert r.quantity("A", "food") == pytest.approx(100.0)
    assert r.quantity("B", "food") == pytest.approx(10.0)
    assert r.quantity("A", "water") == pytest.approx(200.0)
    assert r.quantity("B", "water") == pytest.approx(200.0)
    assert r.total_coverage == pytest.approx(127.5)
    assert r.total_cost == pytest.approx(1500.0)
    assert r.people_covered == pytest.approx(155.0)
    assert r.cost_per_person_covered == pytest.approx(1500.0 / 155.0)


def test_a_binding_floor_moves_supply_to_the_less_severe_district() -> None:
    """A (pop 100, severity 1) and B (pop 100, severity 0.1), one commodity, need 1, supply 100,
    floor 0.5.

    Total need 200, rho = 100/200 = 0.5, share = 50 each, so x >= 0.5 * 50 = 25 each.
    B gets its floor 25 and A the other 75: cov_A = 0.75, cov_B = 0.25.
    Objective = 100 * 0.75 + 10 * 0.25 = 77.5. Without the floor it is 100 (all to A), so the
    equity cost is 22.5.
    """
    base = ProblemSpec(
        districts=(dist("A", 100, 1.0), dist("B", 100, 0.1)),
        commodities=(CommoditySpec("food", 0.0, 1.0, 100.0),),
    )
    from dataclasses import replace

    floor = optimize(replace(base, equity_floor=0.5))
    assert floor.quantity("A", "food") == pytest.approx(75.0)
    assert floor.quantity("B", "food") == pytest.approx(25.0)
    assert floor.total_coverage == pytest.approx(77.5)
    free = optimize(base)
    assert free.total_coverage == pytest.approx(100.0)
    assert free.total_coverage - floor.total_coverage == pytest.approx(22.5)


def test_road_denied_district_is_capped_at_its_air_boat_need_and_unreachable_gets_nothing() -> None:
    """Road district R (pop 100), road-denied B with air/boat 0.3 (pop 100, road 0.05) and
    unreachable U (pop 100, road 0). One commodity need 1, supply 1000 (plenty), severity 1.

    r_R = 100, r_B = 30, r_U = 0, so R gets 100, B gets 30 (not 100) and U gets nothing.
    Unreached people: B 70, U 100.
    """
    spec = ProblemSpec(
        districts=(
            dist("R", 100, 1.0),
            dist("B", 100, 1.0, road=0.05, alt=0.3),
            dist("U", 100, 1.0, road=0.0),
        ),
        commodities=(CommoditySpec("food", 1.0, 1.0, 1000.0),),
    )
    r = optimize(spec)
    assert r.quantity("R", "food") == pytest.approx(100.0)
    assert r.quantity("B", "food") == pytest.approx(30.0)
    assert r.quantity("U", "food") == 0.0
    modes = {c.district_id: (c.access_mode, c.unreached_people) for c in r.coverage}
    assert modes == {"R": ("road", 0.0), "B": ("air_boat", 70.0), "U": ("unreachable", 100.0)}
    assert any("U" in w and "unreachable" in w for w in r.warnings)


def test_zero_people_covered_gives_no_cost_per_person() -> None:
    """LED-R5.2: severity 0 everywhere means weight 0, so nothing is covered by the objective,
    but the allocation may still be anything. With zero supply nothing is delivered at all."""
    spec = ProblemSpec(
        districts=(dist("A", 100, 1.0),),
        commodities=(CommoditySpec("food", 5.0, 1.0, 0.0),),
    )
    r = optimize(spec)
    assert r.people_covered == 0.0
    assert r.cost_per_person_covered is None
    assert r.total_cost == 0.0
