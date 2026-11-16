"""Problem definition and normalisation (design section 2.1 and 2.2).

Everything here is a pure function on plain dataclasses. ``normalize`` turns raw district and
commodity data into the quantities the model needs: usable road access, reachable population,
access mode, unreached people, needs, weights, supply ratios and proportional shares.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

MAX_DISTRICTS = 500
MAX_COMMODITIES = 20
DEFAULT_MIN_ROAD_ACCESS = 0.1

AccessMode = Literal["road", "air_boat", "unreachable"]
FloorPolicy = Literal["relax", "error"]


class InvalidProblem(ValueError):
    """Input violates a validation rule (maps to ``INVALID_INPUT``)."""


@dataclass(frozen=True, slots=True)
class DistrictSpec:
    district_id: str
    population: float
    severity: float
    road_access: float
    alt_delivery_fraction: float = 0.0
    cost_multiplier: float = 1.0


@dataclass(frozen=True, slots=True)
class CommoditySpec:
    commodity_id: str
    unit_cost: float
    per_person_need: float
    supply: float


@dataclass(frozen=True, slots=True)
class ProblemSpec:
    """Raw problem as supplied by the caller (after the dataset lookup, if any)."""

    districts: tuple[DistrictSpec, ...]
    commodities: tuple[CommoditySpec, ...]
    budget: float | None = None
    equity_floor: float = 0.0
    min_road_access: float = DEFAULT_MIN_ROAD_ACCESS
    integer: bool = False
    on_infeasible_floor: FloorPolicy = "relax"
    solver_time_limit_s: float = 10.0


@dataclass(frozen=True, slots=True)
class DistrictInfo:
    district_id: str
    population: float
    severity: float
    access_mode: AccessMode
    reachable: float  # r_d
    unreached: float  # u_d
    weight: float  # w_d = r_d * s_d
    cost_multiplier: float


@dataclass(frozen=True, slots=True)
class CommodityInfo:
    commodity_id: str
    unit_cost: float
    per_person_need: float
    supply: float
    weight: float  # lambda_k
    total_need: float
    supply_ratio: float  # rho_k


@dataclass(frozen=True)
class Problem:
    """Normalised problem. Districts and commodities are sorted by id (deterministic build)."""

    spec: ProblemSpec
    districts: tuple[DistrictInfo, ...]
    commodities: tuple[CommodityInfo, ...]
    need: tuple[tuple[float, ...], ...]  # R[d][k]
    share: tuple[tuple[float, ...], ...]  # proportional share[d][k]
    active: tuple[int, ...] = field(default=())  # district indices with r_d > 0

    @property
    def budget(self) -> float | None:
        return self.spec.budget

    @property
    def integer(self) -> bool:
        return self.spec.integer

    def unit_cost(self, d: int, k: int) -> float:
        """Cost of one unit of commodity k delivered to district d (c_k * m_d)."""
        return self.commodities[k].unit_cost * self.districts[d].cost_multiplier

    def with_integer(self, integer: bool) -> Problem:
        """Same data with the integer flag changed (needs and shares do not depend on it)."""
        from dataclasses import replace

        return replace(self, spec=replace(self.spec, integer=integer))


def _finite(name: str, value: float) -> None:
    if not isinstance(value, int | float) or isinstance(value, bool) or not math.isfinite(value):
        raise InvalidProblem(f"{name} must be a finite number")


def _unit(name: str, value: float) -> None:
    _finite(name, value)
    if not 0.0 <= value <= 1.0:
        raise InvalidProblem(f"{name} must be in [0, 1]")


def validate(spec: ProblemSpec) -> None:
    """Raise ``InvalidProblem`` for any rule violation. No model is built before this passes."""
    if not spec.districts:
        raise InvalidProblem("at least one district is required")
    if len(spec.districts) > MAX_DISTRICTS:
        raise InvalidProblem(f"at most {MAX_DISTRICTS} districts are supported")
    if not spec.commodities:
        raise InvalidProblem("at least one commodity is required")
    if len(spec.commodities) > MAX_COMMODITIES:
        raise InvalidProblem(f"at most {MAX_COMMODITIES} commodities are supported")
    ids = [d.district_id for d in spec.districts]
    if len(set(ids)) != len(ids) or any(not i for i in ids):
        raise InvalidProblem("district ids must be unique and non-empty")
    cids = [c.commodity_id for c in spec.commodities]
    if len(set(cids)) != len(cids) or any(not i for i in cids):
        raise InvalidProblem("commodity ids must be unique and non-empty")
    for d in spec.districts:
        _finite(f"population of {d.district_id}", d.population)
        if d.population < 0:
            raise InvalidProblem(f"population of {d.district_id} must be >= 0")
        _unit(f"severity of {d.district_id}", d.severity)
        _unit(f"road_access of {d.district_id}", d.road_access)
        _unit(f"alt_delivery_fraction of {d.district_id}", d.alt_delivery_fraction)
        _finite(f"cost multiplier of {d.district_id}", d.cost_multiplier)
        if d.cost_multiplier <= 0:
            raise InvalidProblem(f"cost multiplier of {d.district_id} must be > 0")
    for c in spec.commodities:
        _finite(f"unit_cost of {c.commodity_id}", c.unit_cost)
        if c.unit_cost < 0:
            raise InvalidProblem(f"unit_cost of {c.commodity_id} must be >= 0")
        _finite(f"per_person_need of {c.commodity_id}", c.per_person_need)
        if c.per_person_need <= 0:
            raise InvalidProblem(f"per_person_need of {c.commodity_id} must be > 0")
        _finite(f"supply of {c.commodity_id}", c.supply)
        if c.supply < 0:
            raise InvalidProblem(f"supply of {c.commodity_id} must be >= 0")
    if spec.budget is not None:
        _finite("budget", spec.budget)
        if spec.budget < 0:
            raise InvalidProblem("budget must be >= 0")
    _unit("equity_floor", spec.equity_floor)
    _unit("min_road_access", spec.min_road_access)
    _finite("solver_time_limit_s", spec.solver_time_limit_s)
    if spec.solver_time_limit_s <= 0:
        raise InvalidProblem("solver_time_limit_s must be > 0")
    if spec.on_infeasible_floor not in ("relax", "error"):
        raise InvalidProblem("on_infeasible_floor must be 'relax' or 'error'")


def access_mode(d: DistrictSpec, min_road_access: float) -> tuple[AccessMode, float]:
    """Return ``(mode, reachable_fraction)`` for a district (design 2.2 steps 1 to 3).

    Usable road access is ``a`` when ``a >= tau`` and 0 otherwise. A district is ``road`` when
    its usable access is positive, ``air_boat`` when it has none but ``alt > 0``, and
    ``unreachable`` otherwise. (With ``tau = 0`` and ``a = 0`` trucks cannot go either, so that
    corner is ``unreachable`` rather than ``road``.)
    """
    usable = d.road_access if d.road_access >= min_road_access else 0.0
    reach = min(1.0, usable + d.alt_delivery_fraction)
    if usable > 0.0:
        return "road", reach
    if d.alt_delivery_fraction > 0.0:
        return "air_boat", reach
    return "unreachable", 0.0


def normalize(spec: ProblemSpec) -> Problem:
    """Validate and normalise ``spec`` (design 2.2). Districts and commodities sorted by id."""
    validate(spec)
    dspecs = sorted(spec.districts, key=lambda d: d.district_id)
    cspecs = sorted(spec.commodities, key=lambda c: c.commodity_id)
    districts: list[DistrictInfo] = []
    for d in dspecs:
        mode, frac = access_mode(d, spec.min_road_access)
        r = d.population * frac
        districts.append(
            DistrictInfo(
                district_id=d.district_id,
                population=d.population,
                severity=d.severity,
                access_mode=mode,
                reachable=r,
                unreached=max(0.0, d.population - r),
                weight=r * d.severity,
                cost_multiplier=d.cost_multiplier,
            )
        )
    need = tuple(tuple(di.reachable * c.per_person_need for c in cspecs) for di in districts)
    lam = 1.0 / len(cspecs)
    commodities: list[CommodityInfo] = []
    shares_by_k: list[list[float]] = []
    for k, c in enumerate(cspecs):
        total = sum(row[k] for row in need)
        rho = min(1.0, c.supply / total) if total > 0 else 1.0
        commodities.append(
            CommodityInfo(
                commodity_id=c.commodity_id,
                unit_cost=c.unit_cost,
                per_person_need=c.per_person_need,
                supply=c.supply,
                weight=lam,
                total_need=total,
                supply_ratio=rho,
            )
        )
        shares_by_k.append([rho * row[k] for row in need])
    share = tuple(
        tuple(shares_by_k[k][d] for k in range(len(cspecs))) for d in range(len(districts))
    )
    active = tuple(i for i, di in enumerate(districts) if di.reachable > 0.0)
    return Problem(
        spec=spec,
        districts=tuple(districts),
        commodities=tuple(commodities),
        need=need,
        share=share,
        active=active,
    )


def warnings_for(problem: Problem) -> list[str]:
    """Warnings about access: unreachable and air/boat-only districts."""
    out: list[str] = []
    unreachable = [
        d for d in problem.districts if d.access_mode == "unreachable" and d.unreached > 0
    ]
    if unreachable:
        people = sum(d.unreached for d in unreachable)
        names = ", ".join(d.district_id for d in unreachable)
        out.append(
            f"{len(unreachable)} district(s) unreachable (no usable road access and no air/boat "
            f"capacity), nothing allocated, {people:,.0f} people unreached: {names}"
        )
    air = [d for d in problem.districts if d.access_mode == "air_boat"]
    if air:
        names = ", ".join(d.district_id for d in air)
        out.append(
            f"{len(air)} district(s) road-denied, supplied by air/boat capacity only: {names}"
        )
    return out
