"""Safety invariants on every output (LED-R4, LED-R1.5, LED-R1.6).

LED-P1 supply, LED-P2 non-negativity, LED-P4 coverage <= 1, LED-P5 budget,
LED-P17 unreachable districts, LED-P18 road-denied districts. Each runs in LP and MIP mode.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from ledger_strategies import (
    TAU,
    lp_specs,
    mip_specs,
    road_denied_specs,
    unreachable_district_specs,
    valid_specs,
)

from stitch_ledger.core.optimize import optimize
from stitch_ledger.core.postprocess import Result
from stitch_ledger.core.problem import CommoditySpec, DistrictSpec, ProblemSpec, normalize
from stitch_ledger.core.solve import SolverTimeout

EPS = 1e-7

both_modes = valid_specs(max_districts=6, max_commodities=3)


def run(spec: ProblemSpec) -> Result | None:
    try:
        return optimize(spec)
    except SolverTimeout:  # not expected for these sizes; treated as a failure by the caller
        raise


def total_per_commodity(result: Result) -> dict[str, float]:
    out: dict[str, float] = {}
    for _, cid, q in result.allocation:
        out[cid] = out.get(cid, 0.0) + q
    return out


@settings(deadline=None)
@given(both_modes)
def test_p1_allocation_never_exceeds_supply(spec: ProblemSpec) -> None:
    result = optimize(spec)
    supply = {c.commodity_id: c.supply for c in spec.commodities}
    for cid, total in total_per_commodity(result).items():
        assert total <= supply[cid] * (1 + EPS) + 1e-9, (cid, total, supply[cid])


@settings(deadline=None)
@given(both_modes)
def test_p2_allocation_is_non_negative(spec: ProblemSpec) -> None:
    result = optimize(spec)
    assert all(q >= 0.0 and math.isfinite(q) for _, _, q in result.allocation)


@settings(deadline=None)
@given(both_modes)
def test_p4_coverage_never_exceeds_one(spec: ProblemSpec) -> None:
    result = optimize(spec)
    problem = normalize(spec)
    assert all(0.0 <= c.fraction <= 1.0 + 1e-12 for c in result.coverage)
    quantity = {(d, c): q for d, c, q in result.allocation}
    for d in problem.active:
        for k, com in enumerate(problem.commodities):
            q = quantity[problem.districts[d].district_id, com.commodity_id]
            f = min(1.0, q / problem.need[d][k])
            assert 0.0 <= f <= 1.0
    cap = sum(di.weight for di in problem.districts)
    assert result.total_coverage <= cap * (1 + EPS) + 1e-9


@settings(deadline=None)
@given(valid_specs(max_districts=6, max_commodities=3, with_budget=True))
def test_p5_total_cost_never_exceeds_the_budget(spec: ProblemSpec) -> None:
    result = optimize(spec)
    assert spec.budget is not None
    assert result.total_cost <= spec.budget * (1 + EPS) + 1e-9, (result.total_cost, spec.budget)


@settings(deadline=None)
@given(unreachable_district_specs())
def test_p17_unreachable_districts_get_nothing_and_are_listed(spec: ProblemSpec) -> None:
    result = optimize(spec)
    problem = normalize(spec)
    dead = [d for d in problem.districts if d.access_mode == "unreachable" and d.population > 0]
    assert dead, "strategy must produce at least one unreachable district"
    for d in dead:
        assert all(q == 0.0 for dd, _, q in result.allocation if dd == d.district_id)
        line = next(c for c in result.coverage if c.district_id == d.district_id)
        assert line.access_mode == "unreachable"
        assert line.fraction == 0.0
        assert line.unreached_people == d.population
    text = " ".join(result.warnings)
    assert all(d.district_id in text for d in dead)


def _p18_violations(
    spec: ProblemSpec, result: Result, *, round_up: bool
) -> list[tuple[str, str, float, float]]:
    ids = {d.district_id: d for d in spec.districts}
    needs = {c.commodity_id: c.per_person_need for c in spec.commodities}
    bad = []
    for did, cid, q in result.allocation:
        d = ids[did]
        assert d.road_access < TAU
        cap = d.population * d.alt_delivery_fraction * needs[cid]
        if round_up:
            cap = math.ceil(cap - 1e-9)
        if q > cap * (1 + EPS) + 1e-9:
            bad.append((did, cid, q, cap))
    return bad


@settings(deadline=None)
@given(road_denied_specs(integer=False))
def test_p18_road_denied_districts_never_exceed_their_air_boat_capacity(spec: ProblemSpec) -> None:
    assert _p18_violations(spec, optimize(spec), round_up=False) == []


@settings(deadline=None)
@given(road_denied_specs(integer=True))
def test_p18_integer_mode_never_exceeds_capacity_rounded_up_to_a_unit(spec: ProblemSpec) -> None:
    """Integer mode (design 2.5, ``U = ceil(R)``): the cap is the capacity rounded up to a
    whole unit, the same bound as LED-P14."""
    assert _p18_violations(spec, optimize(spec), round_up=True) == []


@pytest.mark.xfail(
    strict=True,
    reason=(
        "SPEC CONFLICT: LED-P18/LED-R1.6 say a road-denied district never receives more than its "
        "air/boat capacity, but design 2.5 sets U = ceil(R) in integer mode, which allows up to "
        "one unit of over-delivery (capacity 0.5 units, 1 unit sent). Implemented per design."
    ),
)
def test_p18_strict_in_integer_mode_regression_half_unit_capacity() -> None:
    spec = ProblemSpec(
        districts=(DistrictSpec("d04", 1.0, 1.0, 0.0, 0.5),),
        commodities=(CommoditySpec("food", 0.0, 1.0, 1.0),),
        integer=True,
    )
    assert _p18_violations(spec, optimize(spec), round_up=False) == []


@settings(deadline=None)
@given(lp_specs(max_districts=8))
def test_safety_holds_for_larger_lp_problems(spec: ProblemSpec) -> None:
    result = optimize(spec)
    supply = {c.commodity_id: c.supply for c in spec.commodities}
    for cid, total in total_per_commodity(result).items():
        assert total <= supply[cid] * (1 + EPS) + 1e-9
    if spec.budget is not None:
        assert result.total_cost <= spec.budget * (1 + EPS) + 1e-9


@settings(deadline=None)
@given(mip_specs())
def test_integer_mode_keeps_the_same_safety_invariants(spec: ProblemSpec) -> None:
    result = optimize(spec)
    supply = {c.commodity_id: c.supply for c in spec.commodities}
    for cid, total in total_per_commodity(result).items():
        assert total <= supply[cid] + 1e-9
    if spec.budget is not None:
        assert result.total_cost <= spec.budget * (1 + EPS) + 1e-9
