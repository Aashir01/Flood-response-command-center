"""LED-P10 (coverage non-increasing in the floor) and LED-P11 (floor 0 is the unconstrained
optimum)."""

from __future__ import annotations

import itertools
from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from ledger_strategies import valid_specs

from stitch_ledger.core.optimize import optimize
from stitch_ledger.core.problem import ProblemSpec, normalize
from stitch_ledger.core.tradeoff import sweep

REL = 1e-6


@settings(deadline=None)
@given(
    valid_specs(integer=False, max_districts=8, max_commodities=3, with_floor=False),
    st.integers(2, 8),
)
def test_p10_total_coverage_is_non_increasing_in_the_floor(spec: ProblemSpec, steps: int) -> None:
    t = sweep(normalize(spec), steps, applied_floor=0.0)
    floors = [p.floor for p in t.points]
    assert floors == sorted(floors) and len(set(floors)) == len(floors)
    feasible = [p for p in t.points if p.status != "infeasible"]
    # feasibility is a prefix of the sorted floors: nothing feasible after the first infeasible
    flags = [p.status != "infeasible" for p in t.points]
    assert flags == sorted(flags, reverse=True)
    values = [p.total_coverage for p in feasible]
    assert all(v is not None for v in values)
    top = max((v for v in values if v is not None), default=0.0)
    for a, b in itertools.pairwise(values):
        assert a is not None and b is not None
        assert b <= a + REL * max(1.0, top), (a, b)
    for p in t.points:
        if p.status == "infeasible":
            assert p.total_coverage is None and p.people_covered is None
            assert p.floor > t.f_max


@settings(deadline=None)
@given(valid_specs(integer=False, max_districts=8, max_commodities=3, with_floor=False))
def test_p11_floor_zero_equals_the_unconstrained_optimum(spec: ProblemSpec) -> None:
    t = sweep(normalize(spec), 3, applied_floor=0.0)
    first = t.points[0]
    assert first.floor == 0.0 and first.total_coverage is not None
    free = optimize(replace(spec, integer=False, equity_floor=0.0))
    assert first.total_coverage == pytest.approx(
        free.total_coverage, rel=REL, abs=1e-9 * max(1.0, free.total_coverage)
    )
    assert first.people_covered == pytest.approx(
        free.people_covered, rel=REL, abs=1e-9 * max(1.0, free.people_covered)
    )
