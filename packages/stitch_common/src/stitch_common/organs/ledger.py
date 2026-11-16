"""ledger-mcp tool I/O (mcp-contracts.md section 6 and resource in 8b), contract v0.3.

Ambiguities and the reading chosen:

* ``supply`` keys must all be commodity ids. A commodity with no entry is not rejected here;
  the solver decides what a missing entry means.
* ``commodities`` is non-empty with unique ids; ``districts`` (when given) has unique ids.
* ``equity.floor_applied <= equity.floor_requested`` (relaxing never raises the floor).
* ``status = "infeasible"`` requires ``infeasibility_reason``.
* A tradeoff step is ``infeasible`` iff both its coverage numbers are null.
* ``solver_time_limit_s`` must be positive.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from stitch_common.base import Contract
from stitch_common.types import NonNeg, Unit

Status = Literal["optimal", "feasible", "infeasible"]
CONSTRAINT_PATTERN = r"^(supply:.+|budget|equity_floor|min_coverage:.+)$"


class DistrictInput(Contract):
    district_id: str = Field(min_length=1)
    population_affected: int = Field(ge=0)
    severity: Unit
    road_access: Unit
    alt_delivery_fraction: Unit = 0.0
    unit_cost_multiplier: float | None = Field(default=None, gt=0.0)


class Commodity(Contract):
    id: str = Field(min_length=1)
    name: str
    unit: str
    unit_cost: NonNeg
    per_person_need: float = Field(gt=0.0)


class OptimizeAllocationIn(Contract):
    scenario_id: str = Field(min_length=1)
    districts: list[DistrictInput] | None = None
    min_road_access: Unit = 0.1
    commodities: list[Commodity] = Field(min_length=1)
    supply: dict[str, NonNeg]
    budget: NonNeg | None = None
    equity_floor: Unit | None = None
    on_infeasible_floor: Literal["relax", "error"] = "relax"
    integer: bool = True
    solver_time_limit_s: float = Field(default=10.0, gt=0.0)

    @model_validator(mode="after")
    def _consistent(self) -> OptimizeAllocationIn:
        ids = [c.id for c in self.commodities]
        if len(set(ids)) != len(ids):
            raise ValueError("commodity ids must be unique")
        unknown = set(self.supply) - set(ids)
        if unknown:
            raise ValueError(f"supply names unknown commodities: {sorted(unknown)}")
        if self.districts is not None:
            dids = [d.district_id for d in self.districts]
            if len(set(dids)) != len(dids):
                raise ValueError("district ids must be unique")
        return self


class AllocationLine(Contract):
    district_id: str
    commodity_id: str
    quantity: NonNeg


class CoverageLine(Contract):
    district_id: str
    fraction: Unit
    access_mode: Literal["road", "air_boat", "unreachable"]
    unreached_people: NonNeg


class Equity(Contract):
    floor_requested: Unit
    floor_applied: Unit
    max_feasible_floor: Unit

    @model_validator(mode="after")
    def _applied_not_above_requested(self) -> Equity:
        if self.floor_applied > self.floor_requested:
            raise ValueError("floor_applied must not exceed floor_requested")
        return self


class CostBenefit(Contract):
    cost_per_person_covered: NonNeg
    people_covered: NonNeg


class SolverInfo(Contract):
    name: str
    version: str
    wall_time_s: NonNeg


class OptimizeAllocationOut(Contract):
    status: Status
    allocation: list[AllocationLine]
    coverage: list[CoverageLine]
    equity: Equity
    total_coverage: NonNeg
    total_cost: NonNeg
    optimality_gap: NonNeg | None
    cost_benefit: CostBenefit
    solver: SolverInfo
    infeasibility_reason: str | None = None

    @model_validator(mode="after")
    def _reason_when_infeasible(self) -> OptimizeAllocationOut:
        if self.status == "infeasible" and not self.infeasibility_reason:
            raise ValueError("infeasible requires infeasibility_reason")
        return self


class SensitivityReportIn(Contract):
    run_id: str = Field(min_length=1)
    floor_steps: int = Field(default=11, ge=2, le=21)


class ShadowPrice(Contract):
    constraint: str = Field(pattern=CONSTRAINT_PATTERN)
    value: float
    unit: str
    binding: bool


class ReducedCost(Contract):
    district_id: str
    commodity_id: str
    value: float


class ConstraintRange(Contract):
    constraint: str
    allowable_increase: float
    allowable_decrease: float


class TradeoffPoint(Contract):
    min_coverage_floor: Unit
    status: Status
    total_coverage: float | None
    people_covered: float | None

    @model_validator(mode="after")
    def _null_iff_infeasible(self) -> TradeoffPoint:
        empty = self.total_coverage is None and self.people_covered is None
        full = self.total_coverage is not None and self.people_covered is not None
        if self.status == "infeasible" and not empty:
            raise ValueError("infeasible step must have null coverage numbers")
        if self.status != "infeasible" and not full:
            raise ValueError("feasible step needs total_coverage and people_covered")
        return self


class SensitivityReportOut(Contract):
    shadow_prices: list[ShadowPrice]
    reduced_costs: list[ReducedCost]
    ranges: list[ConstraintRange]
    basis: Literal["lp_relaxation"]
    equity_tradeoff: list[TradeoffPoint]
    equity_cost: float | None
    notes: list[str]


class ScenarioDistrict(Contract):
    """Item of the resource ``ledger://scenario/{scenario_id}/districts``."""

    district_id: str = Field(min_length=1)
    name: str
    population: int = Field(ge=0)
    road_access: Unit
    alt_delivery_fraction: Unit
    default_severity: Unit
