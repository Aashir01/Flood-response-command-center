"""Shared Hypothesis strategies for the Ledger tests (design section 7).

``valid_specs()`` generates 1 to 12 districts, 1 to 4 commodities, supplies from 0 to 3x the total
need, an optional budget, an optional floor and optional air/boat capacity. It deliberately
includes the edge cases from the design: zero population, access exactly at and just below the
usable-access threshold, severity 0, zero supply, floors above ``max_feasible_floor`` and tiny
budgets.
"""

from __future__ import annotations

import math
from typing import Any

from hypothesis import strategies as st

from stitch_ledger.core.problem import CommoditySpec, DistrictSpec, ProblemSpec

TAU = 0.1
IDS = [f"d{i:02d}" for i in range(40)]
CIDS = ["food", "medical", "shelter", "water"]

populations = st.one_of(
    st.just(0.0),
    st.integers(1, 2_000).map(float),
    st.integers(1, 1_000_000).map(float),
)
severities = st.one_of(
    st.just(0.0),
    st.just(1.0),
    st.floats(0.0, 1.0, allow_nan=False, allow_infinity=False),
)
road_accesses = st.one_of(
    st.just(0.0),
    st.just(TAU),
    st.just(math.nextafter(TAU, 0.0)),
    st.just(1.0),
    st.floats(0.0, 1.0, allow_nan=False, allow_infinity=False),
)
alt_fractions = st.one_of(
    st.just(0.0),
    st.just(0.0),
    st.floats(0.0, 1.0, allow_nan=False, allow_infinity=False),
)
multipliers = st.one_of(st.just(1.0), st.floats(0.5, 3.0, allow_nan=False, allow_infinity=False))
unit_costs = st.one_of(st.just(0.0), st.floats(0.1, 100.0, allow_nan=False, allow_infinity=False))
needs_pp = st.floats(0.1, 10.0, allow_nan=False, allow_infinity=False)
supply_factors = st.one_of(
    st.just(0.0),
    st.just(1.0),
    st.floats(0.0, 3.0, allow_nan=False, allow_infinity=False),
)
floors = st.one_of(
    st.just(0.0),
    st.just(1.0),
    st.floats(0.0, 1.0, allow_nan=False, allow_infinity=False),
)


@st.composite
def districts_strategy(
    draw: st.DrawFn,
    *,
    min_size: int = 1,
    max_size: int = 12,
    access: st.SearchStrategy[float] = road_accesses,
    alt: st.SearchStrategy[float] = alt_fractions,
    severity: st.SearchStrategy[float] = severities,
    population: st.SearchStrategy[float] = populations,
) -> tuple[DistrictSpec, ...]:
    ids = draw(st.lists(st.sampled_from(IDS), min_size=min_size, max_size=max_size, unique=True))
    return tuple(
        DistrictSpec(
            district_id=i,
            population=draw(population),
            severity=draw(severity),
            road_access=draw(access),
            alt_delivery_fraction=draw(alt),
            cost_multiplier=draw(multipliers),
        )
        for i in ids
    )


@st.composite
def valid_specs(
    draw: st.DrawFn,
    *,
    integer: bool | None = None,
    min_commodities: int = 1,
    max_commodities: int = 4,
    max_districts: int = 12,
    with_budget: bool | None = None,
    with_floor: bool | None = None,
    policy: str | None = None,
    districts: st.SearchStrategy[tuple[DistrictSpec, ...]] | None = None,
) -> ProblemSpec:
    """A valid ``ProblemSpec``. ``None`` options are drawn at random."""
    ds = draw(districts if districts is not None else districts_strategy(max_size=max_districts))
    cids = draw(
        st.lists(
            st.sampled_from(CIDS), min_size=min_commodities, max_size=max_commodities, unique=True
        )
    )
    reach_pop = sum(d.population * (1.0 if d.road_access >= TAU else 0.0) for d in ds)
    total_pop = max(sum(d.population for d in ds), reach_pop, 1.0)
    commodities: list[CommoditySpec] = []
    for cid in cids:
        n = draw(needs_pp)
        factor = draw(supply_factors)
        commodities.append(
            CommoditySpec(cid, draw(unit_costs), n, float(round(factor * total_pop * n)))
        )
    use_budget = draw(st.booleans()) if with_budget is None else with_budget
    budget: float | None = None
    if use_budget:
        full = sum(c.unit_cost * c.per_person_need * total_pop for c in commodities)
        budget = draw(
            st.one_of(
                st.just(0.0),
                st.floats(0.0, 1e-3, allow_nan=False, allow_infinity=False),
                st.floats(0.0, max(full, 1.0) * 1.5, allow_nan=False, allow_infinity=False),
            )
        )
    use_floor = draw(st.booleans()) if with_floor is None else with_floor
    floor = draw(floors) if use_floor else 0.0
    return ProblemSpec(
        districts=ds,
        commodities=tuple(commodities),
        budget=budget,
        equity_floor=floor,
        min_road_access=TAU,
        integer=draw(st.booleans()) if integer is None else integer,
        on_infeasible_floor=policy
        if policy is not None
        else draw(  # type: ignore[arg-type]
            st.sampled_from(["relax", "error"])
        ),
        solver_time_limit_s=20.0,
    )


def lp_specs(**kw: Any) -> st.SearchStrategy[ProblemSpec]:
    return valid_specs(integer=False, **kw)


def mip_specs(**kw: Any) -> st.SearchStrategy[ProblemSpec]:
    # Integer problems are kept small so SCIP proves optimality quickly.
    kw.setdefault("max_districts", 6)
    kw.setdefault("max_commodities", 3)
    return valid_specs(integer=True, **kw)


def unreachable_district_specs() -> st.SearchStrategy[ProblemSpec]:
    """Districts with no usable road access and no air/boat capacity (LED-P17)."""
    dead = districts_strategy(
        access=st.one_of(st.just(0.0), st.floats(0.0, math.nextafter(TAU, 0.0))),
        alt=st.just(0.0),
        population=st.integers(1, 100_000).map(float),
    )
    return st.tuples(valid_specs(), dead).map(_merge_dead)


def _merge_dead(pair: tuple[ProblemSpec, tuple[DistrictSpec, ...]]) -> ProblemSpec:
    from dataclasses import replace

    spec, dead = pair
    taken = {d.district_id for d in spec.districts}
    extra = tuple(d for d in dead if d.district_id not in taken)
    return replace(spec, districts=spec.districts + extra)


def road_denied_specs() -> st.SearchStrategy[ProblemSpec]:
    """Every district road-denied, with air/boat capacity (LED-P18)."""
    denied = districts_strategy(
        access=st.floats(0.0, math.nextafter(TAU, 0.0), allow_nan=False),
        alt=st.floats(0.01, 1.0, allow_nan=False),
    )
    return valid_specs(districts=denied)


_BAD = [
    ("population", -1.0),
    ("population", math.nan),
    ("severity", 1.5),
    ("severity", -0.1),
    ("road_access", 2.0),
    ("road_access", math.inf),
    ("alt_delivery_fraction", -0.5),
    ("cost_multiplier", 0.0),
]


@st.composite
def invalid_specs(draw: st.DrawFn) -> ProblemSpec:
    """A valid spec with exactly one rule broken (LED-R2.1, LED-R2.2)."""
    from dataclasses import replace

    spec = draw(valid_specs())
    kind = draw(st.sampled_from(["district", "commodity", "budget", "floor", "dup", "empty"]))
    if kind == "district":
        i = draw(st.integers(0, len(spec.districts) - 1))
        field, value = draw(st.sampled_from(_BAD))
        ds = list(spec.districts)
        ds[i] = replace(ds[i], **{field: value})
        return replace(spec, districts=tuple(ds))
    if kind == "commodity":
        c = replace(
            spec.commodities[0],
            **draw(
                st.sampled_from(
                    [
                        {"unit_cost": -1.0},
                        {"per_person_need": 0.0},
                        {"supply": -5.0},
                        {"supply": math.nan},
                    ]
                )
            ),
        )
        return replace(spec, commodities=(c, *spec.commodities[1:]))
    if kind == "budget":
        return replace(spec, budget=draw(st.sampled_from([-1.0, math.nan, math.inf])))
    if kind == "floor":
        return replace(spec, equity_floor=draw(st.sampled_from([-0.1, 1.5, math.nan])))
    if kind == "dup":
        return replace(spec, districts=(*spec.districts, spec.districts[0]))
    return replace(spec, districts=())
