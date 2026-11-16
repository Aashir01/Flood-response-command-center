"""LED-P3 monotonicity, LED-P7 symmetry, LED-P8 scale invariance, LED-P13 baseline."""

from __future__ import annotations

import dataclasses
import random

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from ledger_strategies import (
    districts_strategy,
    lp_specs,
    mip_specs,
    objective_scale,
    valid_specs,
)

from stitch_ledger.core.baseline import proportional_baseline
from stitch_ledger.core.optimize import optimize
from stitch_ledger.core.problem import CommoditySpec, DistrictSpec, ProblemSpec, normalize

REL = 1e-6


def close(a: float, b: float, rel: float = REL) -> bool:
    return abs(a - b) <= rel * max(1.0, abs(a), abs(b))


@settings(deadline=None)
@given(
    lp_specs(max_districts=8, with_floor=False),
    st.integers(0, 3),
    st.floats(0.0, 1e6, allow_nan=False),
)
def test_p3_more_supply_never_lowers_total_coverage_lp(
    spec: ProblemSpec, which: int, delta: float
) -> None:
    k = which % len(spec.commodities)
    more = list(spec.commodities)
    more[k] = dataclasses.replace(more[k], supply=more[k].supply + delta)
    bigger = dataclasses.replace(spec, commodities=tuple(more))
    low, high = optimize(spec), optimize(bigger)
    assert high.total_coverage >= low.total_coverage - REL * max(1.0, low.total_coverage)


@settings(deadline=None)
@given(
    mip_specs(with_floor=False),
    st.integers(0, 2),
    st.integers(0, 50).map(float),
)
def test_p3_more_supply_never_lowers_total_coverage_mip_when_proven_optimal(
    spec: ProblemSpec, which: int, delta: float
) -> None:
    k = which % len(spec.commodities)
    more = list(spec.commodities)
    more[k] = dataclasses.replace(more[k], supply=more[k].supply + delta)
    low, high = optimize(spec), optimize(dataclasses.replace(spec, commodities=tuple(more)))
    assume(low.status == "optimal" and high.status == "optimal")
    assert high.total_coverage >= low.total_coverage - REL * max(1.0, low.total_coverage)


@settings(deadline=None)
@given(lp_specs(max_districts=8))
def test_p3_with_a_floor_coverage_is_still_at_least_the_proportional_baseline(
    spec: ProblemSpec,
) -> None:
    """The floor makes ``share`` (which depends on S) part of the constraints, so strict
    monotonicity is stated at floor 0 (design 7). With a floor the guarantee is P13."""
    problem = normalize(spec)
    result = optimize(spec)
    assume(result.status != "infeasible")
    base = proportional_baseline(problem)
    assert result.total_coverage >= base.total_coverage - REL * objective_scale(problem)


@settings(deadline=None)
@given(valid_specs(max_districts=8, max_commodities=3), st.randoms(use_true_random=False))
def test_p7_permuting_and_relabelling_districts_keeps_total_coverage(
    spec: ProblemSpec, rnd: random.Random
) -> None:
    ds = list(spec.districts)
    rnd.shuffle(ds)
    labels = [f"z{i:02d}" for i in range(len(ds))]
    rnd.shuffle(labels)
    relabelled = tuple(
        dataclasses.replace(d, district_id=label) for d, label in zip(ds, labels, strict=True)
    )
    other = dataclasses.replace(spec, districts=relabelled)
    a, b = optimize(spec), optimize(other)
    assert a.status == b.status
    if a.status == "optimal":
        assert close(a.total_coverage, b.total_coverage)


@settings(deadline=None)
@given(lp_specs(max_districts=8), st.sampled_from([0.25, 0.5, 2.0, 3.0, 10.0]))
def test_p8_scaling_population_supply_and_budget_scales_total_coverage(
    spec: ProblemSpec, factor: float
) -> None:
    scaled = dataclasses.replace(
        spec,
        districts=tuple(
            dataclasses.replace(d, population=d.population * factor) for d in spec.districts
        ),
        commodities=tuple(
            dataclasses.replace(c, supply=c.supply * factor) for c in spec.commodities
        ),
        budget=None if spec.budget is None else spec.budget * factor,
    )
    a, b = optimize(spec), optimize(scaled)
    assert a.status == b.status
    assert a.floor_applied == pytest.approx(b.floor_applied, rel=1e-9, abs=1e-12)
    assert close(a.total_coverage * factor, b.total_coverage)


@settings(deadline=None)
@given(
    districts_strategy(max_size=8, severity=st.floats(0.01, 1.0)),
    st.sampled_from([0.5, 2.0, 7.0]),
    st.floats(0.0, 3.0),
)
def test_p8_coverage_fractions_are_unchanged_when_the_optimum_is_unique(
    ds: tuple[DistrictSpec, ...], factor: float, supply_factor: float
) -> None:
    """One commodity, no budget, pairwise different severities: the greedy optimum is unique."""
    assume(len({d.severity for d in ds}) == len(ds))
    total = sum(d.population for d in ds)
    spec = ProblemSpec(
        districts=ds, commodities=(CommoditySpec("food", 1.0, 1.0, supply_factor * total),)
    )
    scaled = dataclasses.replace(
        spec,
        districts=tuple(dataclasses.replace(d, population=d.population * factor) for d in ds),
        commodities=(CommoditySpec("food", 1.0, 1.0, supply_factor * total * factor),),
    )
    a, b = optimize(spec), optimize(scaled)
    for ca, cb in zip(a.coverage, b.coverage, strict=True):
        assert ca.fraction == pytest.approx(cb.fraction, abs=1e-6)


@settings(deadline=None)
@given(lp_specs(max_districts=8))
def test_p13_lp_optimum_is_at_least_the_proportional_baseline(spec: ProblemSpec) -> None:
    result = optimize(spec)
    assume(result.status != "infeasible")
    problem = normalize(spec)
    base = proportional_baseline(problem)
    assert result.total_coverage >= base.total_coverage - REL * objective_scale(problem)


@settings(deadline=None)
@given(mip_specs(with_floor=False))
def test_p13_mip_optimum_is_at_least_the_floored_baseline_when_proven_optimal(
    spec: ProblemSpec,
) -> None:
    result = optimize(spec)
    assume(result.status == "optimal")
    problem = normalize(spec)
    base = proportional_baseline(problem)
    assert result.total_coverage >= base.total_coverage - REL * objective_scale(problem)
