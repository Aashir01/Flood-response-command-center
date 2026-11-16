"""LED-P12 (greedy-by-severity oracle) and LED-P16 (floor 1 is the proportional allocation)."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from ledger_strategies import lp_specs, valid_specs

from stitch_ledger.core.optimize import optimize
from stitch_ledger.core.problem import CommoditySpec, DistrictSpec, ProblemSpec

REL = 1e-6


def greedy_total_coverage(spec: ProblemSpec) -> float:
    """Independent reference for one commodity, no budget, no floor.

    Written from the raw spec only (it does not use ``normalize``): reachable population from
    the access rule, then fill districts in decreasing severity, each up to its need.
    """
    (com,) = spec.commodities
    tau = spec.min_road_access
    remaining = com.supply
    total = 0.0
    rows = []
    for d in spec.districts:
        usable = d.road_access if d.road_access >= tau else 0.0
        reach = min(1.0, usable + d.alt_delivery_fraction)
        if usable == 0.0 and d.alt_delivery_fraction == 0.0:
            reach = 0.0
        rows.append((d.severity, d.population * reach, d.district_id))
    for severity, reachable, _ in sorted(rows, key=lambda r: (-r[0], r[2])):
        need = reachable * com.per_person_need
        if need <= 0:
            continue
        give = min(need, remaining)
        remaining -= give
        total += reachable * severity * (give / need)
    return total


single_commodity = lp_specs(
    min_commodities=1, max_commodities=1, with_budget=False, with_floor=False
)


@settings(deadline=None)
@given(single_commodity)
def test_p12_lp_optimum_equals_greedy_by_severity(spec: ProblemSpec) -> None:
    result = optimize(spec)
    assert result.status == "optimal"
    expected = greedy_total_coverage(spec)
    assert result.total_coverage == pytest.approx(expected, rel=REL, abs=1e-6)


@settings(deadline=None)
@given(valid_specs(integer=False, with_budget=False))
def test_p16_floor_one_without_budget_is_the_proportional_allocation(spec: ProblemSpec) -> None:
    from dataclasses import replace

    from stitch_ledger.core.problem import normalize

    spec = replace(spec, equity_floor=1.0)
    problem = normalize(spec)
    result = optimize(spec)
    assert result.status == "optimal" and result.floor_applied == 1.0
    for d in problem.active:
        for k, c in enumerate(problem.commodities):
            got = result.quantity(problem.districts[d].district_id, c.commodity_id)
            scale = max(1.0, problem.need[d][k])
            assert abs(got - problem.share[d][k]) <= REL * scale


def test_greedy_reference_matches_a_trivial_case() -> None:
    spec = ProblemSpec(
        districts=(DistrictSpec("a", 100, 0.5, 1.0), DistrictSpec("b", 100, 1.0, 1.0)),
        commodities=(CommoditySpec("f", 0.0, 1.0, 150.0),),
    )
    assert greedy_total_coverage(spec) == pytest.approx(100 * 1.0 + 100 * 0.5 * 0.5)
