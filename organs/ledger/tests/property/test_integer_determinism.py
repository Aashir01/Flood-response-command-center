"""LED-P14 (integer outputs bounded by ceil(need)) and LED-P9 (determinism)."""

from __future__ import annotations

import dataclasses
import math

from hypothesis import given, settings
from ledger_strategies import lp_specs, mip_specs, valid_specs

from stitch_ledger.core.optimize import optimize
from stitch_ledger.core.postprocess import Result
from stitch_ledger.core.problem import ProblemSpec, normalize


def comparable(result: Result) -> dict[str, object]:
    """The result minus wall-clock time (LED-P9 compares ``data`` minus ``wall_time_s``)."""
    return {**dataclasses.asdict(result), "wall_time_s": 0.0}


@settings(deadline=None)
@given(mip_specs())
def test_p14_integer_mode_gives_integral_quantities_at_most_ceil_of_need(
    spec: ProblemSpec,
) -> None:
    problem = normalize(spec)
    result = optimize(spec)
    need = {
        (problem.districts[d].district_id, c.commodity_id): problem.need[d][k]
        for d in problem.active
        for k, c in enumerate(problem.commodities)
    }
    for did, cid, q in result.allocation:
        assert q == math.floor(q), (did, cid, q)
        assert q <= math.ceil(need[did, cid]), (did, cid, q, need[did, cid])


@settings(deadline=None)
@given(valid_specs(max_districts=6, max_commodities=3))
def test_p9_output_is_a_deterministic_function_of_input(spec: ProblemSpec) -> None:
    assert comparable(optimize(spec)) == comparable(optimize(spec))


@settings(deadline=None)
@given(lp_specs(max_districts=8))
def test_p9_holds_when_the_district_input_order_is_reversed_for_lp(spec: ProblemSpec) -> None:
    """Construction is sorted by id, so even the order of the input does not matter."""
    flipped = dataclasses.replace(spec, districts=tuple(reversed(spec.districts)))
    assert comparable(optimize(spec)) == comparable(optimize(flipped))
