"""Validation rules and access modes (LED-R1.4 to R1.6, LED-R2.1, LED-R2.2, design 2.2)."""

from __future__ import annotations

import math
from dataclasses import replace
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from ledger_strategies import invalid_specs

from stitch_ledger.core.optimize import optimize
from stitch_ledger.core.problem import (
    MAX_COMMODITIES,
    MAX_DISTRICTS,
    CommoditySpec,
    DistrictSpec,
    InvalidProblem,
    ProblemSpec,
    access_mode,
    normalize,
    validate,
    warnings_for,
)

TAU = 0.1
FOOD = CommoditySpec("food", unit_cost=10.0, per_person_need=2.0, supply=100.0)


def spec_of(*districts: DistrictSpec, **kw: object) -> ProblemSpec:
    return ProblemSpec(districts=tuple(districts), commodities=(FOOD,), **kw)  # type: ignore[arg-type]


def district(**kw: object) -> DistrictSpec:
    base = {"district_id": "a", "population": 100.0, "severity": 0.5, "road_access": 1.0}
    return DistrictSpec(**{**base, **kw})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad",
    [
        {"population": -1.0},
        {"population": math.nan},
        {"population": math.inf},
        {"severity": 1.01},
        {"severity": -0.01},
        {"road_access": 1.5},
        {"road_access": math.nan},
        {"alt_delivery_fraction": 2.0},
        {"cost_multiplier": 0.0},
        {"cost_multiplier": -1.0},
    ],
)
def test_invalid_district_fields_are_rejected(bad: dict[str, float]) -> None:
    with pytest.raises(InvalidProblem):
        validate(spec_of(district(**bad)))


@pytest.mark.parametrize(
    "bad",
    [
        {"unit_cost": -1.0},
        {"unit_cost": math.inf},
        {"per_person_need": 0.0},
        {"per_person_need": -1.0},
        {"supply": -1.0},
        {"supply": math.nan},
    ],
)
def test_invalid_commodity_fields_are_rejected(bad: dict[str, float]) -> None:
    with pytest.raises(InvalidProblem):
        validate(replace(spec_of(district()), commodities=(replace(FOOD, **bad),)))


@pytest.mark.parametrize(
    "change",
    [
        {"budget": -1.0},
        {"budget": math.inf},
        {"equity_floor": 1.1},
        {"equity_floor": -0.1},
        {"min_road_access": 2.0},
        {"solver_time_limit_s": 0.0},
        {"solver_time_limit_s": math.nan},
        {"on_infeasible_floor": "maybe"},
    ],
)
def test_invalid_scalar_fields_are_rejected(change: dict[str, object]) -> None:
    with pytest.raises(InvalidProblem):
        validate(replace(spec_of(district()), **change))


def test_structure_rules() -> None:
    with pytest.raises(InvalidProblem, match="at least one district"):
        validate(spec_of())
    with pytest.raises(InvalidProblem, match="unique"):
        validate(spec_of(district(), district()))
    with pytest.raises(InvalidProblem, match="unique"):
        validate(replace(spec_of(district()), commodities=(FOOD, FOOD)))
    with pytest.raises(InvalidProblem, match="at least one commodity"):
        validate(replace(spec_of(district()), commodities=()))


def test_size_caps() -> None:
    many = tuple(district(district_id=f"d{i}") for i in range(MAX_DISTRICTS + 1))
    with pytest.raises(InvalidProblem, match="districts"):
        validate(spec_of(*many))
    assert validate(spec_of(*many[:MAX_DISTRICTS])) is None
    coms = tuple(replace(FOOD, commodity_id=f"c{i}") for i in range(MAX_COMMODITIES + 1))
    with pytest.raises(InvalidProblem, match="commodities"):
        validate(replace(spec_of(district()), commodities=coms))


@pytest.mark.parametrize(
    ("access", "alt", "mode", "reach"),
    [
        (1.0, 0.0, "road", 1.0),
        (0.6, 0.1, "road", 0.7),
        (0.95, 0.2, "road", 1.0),  # capped at 1
        (TAU, 0.0, "road", TAU),  # exactly at the threshold is usable
        (math.nextafter(TAU, 0.0), 0.0, "unreachable", 0.0),  # just below, no alt
        (math.nextafter(TAU, 0.0), 0.3, "air_boat", 0.3),  # road ignored, alt carries
        (0.0, 0.0, "unreachable", 0.0),
        (0.0, 0.4, "air_boat", 0.4),
    ],
)
def test_access_mode_table_at_the_threshold_boundary(
    access: float, alt: float, mode: str, reach: float
) -> None:
    got_mode, got_reach = access_mode(district(road_access=access, alt_delivery_fraction=alt), TAU)
    assert (got_mode, got_reach) == (mode, pytest.approx(reach))


def test_zero_threshold_with_zero_access_is_unreachable_not_road() -> None:
    assert access_mode(district(road_access=0.0), 0.0) == ("unreachable", 0.0)


def test_normalize_derives_reach_need_weight_and_share() -> None:
    """Hand calculation. Districts a (road 0.5, sev 0.8, pop 1000) and b (road-denied 0.05,
    air/boat 0.2, sev 0.5, pop 500). Commodity food: need 2 per person, supply 1000.

    r_a = 500, r_b = 100. R_a = 1000, R_b = 200, total 1200, rho = 1000/1200 = 5/6.
    w_a = 500 * 0.8 = 400, w_b = 100 * 0.5 = 50. share_a = 833.33, share_b = 166.67.
    u_a = 500, u_b = 400.
    """
    food = replace(FOOD, supply=1000.0)
    spec = ProblemSpec(
        districts=(
            district(
                district_id="b",
                population=500.0,
                severity=0.5,
                road_access=0.05,
                alt_delivery_fraction=0.2,
            ),
            district(district_id="a", population=1000.0, severity=0.8, road_access=0.5),
        ),
        commodities=(food,),
        min_road_access=TAU,
    )
    p = normalize(spec)
    assert [d.district_id for d in p.districts] == ["a", "b"]  # sorted by id
    a, b = p.districts
    assert (a.access_mode, b.access_mode) == ("road", "air_boat")
    assert (a.reachable, b.reachable) == (pytest.approx(500.0), pytest.approx(100.0))
    assert (a.unreached, b.unreached) == (pytest.approx(500.0), pytest.approx(400.0))
    assert (a.weight, b.weight) == (pytest.approx(400.0), pytest.approx(50.0))
    assert p.need[0][0] == pytest.approx(1000.0) and p.need[1][0] == pytest.approx(200.0)
    assert p.commodities[0].supply_ratio == pytest.approx(5 / 6)
    assert p.share[0][0] == pytest.approx(1000 * 5 / 6)
    assert p.share[1][0] == pytest.approx(200 * 5 / 6)


def test_supply_ratio_is_capped_at_one_and_is_one_without_need() -> None:
    short = normalize(spec_of(district()))
    assert short.commodities[0].supply_ratio == pytest.approx(0.5)  # supply 100, need 200
    plenty = normalize(replace(spec_of(district()), commodities=(replace(FOOD, supply=1e9),)))
    assert plenty.commodities[0].supply_ratio == 1.0
    nobody = normalize(spec_of(district(population=0.0)))
    assert nobody.commodities[0].total_need == 0.0 and nobody.commodities[0].supply_ratio == 1.0


def test_unreachable_and_air_boat_districts_produce_warnings() -> None:
    p = normalize(
        spec_of(
            district(district_id="dead", road_access=0.0, population=300.0),
            district(district_id="boat", road_access=0.0, alt_delivery_fraction=0.5),
            district(district_id="ok"),
        )
    )
    text = " ".join(warnings_for(p))
    assert "dead" in text and "300" in text and "boat" in text
    assert "ok" not in text.replace("road-denied", "")
    assert [p.districts[i].district_id for i in p.active] == ["boat", "ok"]


@settings(max_examples=60, deadline=None)
@given(invalid_specs())
def test_invalid_input_never_reaches_the_solver(bad: ProblemSpec) -> None:
    """LED-R2.2: every invalid class is rejected before any model is built."""
    with (
        patch("stitch_ledger.core.optimize.build", side_effect=AssertionError("model built")),
        pytest.raises(InvalidProblem),
    ):
        optimize(bad)
