"""Ledger service: the layer between the MCP tools and the pure ``core`` (design sections 4 and 6).

It resolves districts (override or committed dataset), maps contract models to core problems,
maps core results and failures back to contract models and ``ToolFailure`` codes, and keeps runs
in the ``RunStore`` so that ``sensitivity_report`` can find them by ``run_id``. All I/O lives
here, none in ``core``.

Decisions recorded here (also in ``docs/ledger-model.md``):

* A commodity with no entry in ``supply`` has supply 0, with a warning.
* ``solver_time_limit_s`` is capped at 30 s.
* ``cost_per_person_covered`` is 0.0 when nobody is covered, because contract v0.4 types it as a
  number. A warning says so. LED-R5.2 asks for null (see ``docs/decisions.md``).
* With integer runs the equity trade-off and shadow prices come from the LP relaxation.
* Mode (contract v0.4 optional ``mode`` input): the Ledger never uses the network. With the
  committed dataset the result is always ``mode = demo``, and a ``live`` request adds a
  ``MODE_FALLBACK`` warning. With caller-supplied ``districts`` the result carries the requested
  mode (else ``STITCH_MODE``), because the inputs then come from the caller.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ortools.linear_solver import pywraplp

from stitch_common.organs.ledger import (
    AllocationLine,
    ConstraintRange,
    CostBenefit,
    CoverageLine,
    Equity,
    OptimizeAllocationIn,
    OptimizeAllocationOut,
    ReducedCost,
    ScenarioDistrict,
    SensitivityReportIn,
    SensitivityReportOut,
    ShadowPrice,
    SolverInfo,
    TradeoffPoint,
)
from stitch_common.provenance import DataSource, ModelInfo, canonical_json
from stitch_common.tooling import Outcome, ToolFailure, current_mode
from stitch_common.types import Mode
from stitch_ledger.core.optimize import optimize
from stitch_ledger.core.postprocess import Result
from stitch_ledger.core.problem import (
    CommoditySpec,
    DistrictSpec,
    InvalidProblem,
    ProblemSpec,
    normalize,
)
from stitch_ledger.core.ranges import allowable_ranges
from stitch_ledger.core.sensitivity import analyze
from stitch_ledger.core.solve import SolverError, SolverTimeout
from stitch_ledger.core.tradeoff import lp_f_max, sweep
from stitch_ledger.data.loader import (
    DatasetError,
    Scenario,
    UnknownScenario,
    load_scenario,
)
from stitch_ledger.store import RunStore

MAX_TIME_LIMIT_S = 30.0
DEFAULT_SCENARIO = "demo-sindh-2022"
DB_ENV = "STITCH_LEDGER_DB"


class LedgerService:
    def __init__(self, store: RunStore | None = None, demo_root: Path | None = None) -> None:
        self.store = store if store is not None else RunStore(os.environ.get(DB_ENV) or None)
        self.demo_root = demo_root

    # ------------------------------------------------------------------ resolve

    def _scenario(self, scenario_id: str) -> Scenario:
        try:
            return load_scenario(scenario_id, self.demo_root)
        except UnknownScenario:
            raise ToolFailure("NOT_FOUND", f"unknown scenario_id {scenario_id!r}") from None
        except DatasetError as exc:
            raise ToolFailure("INTERNAL", f"demo dataset unusable: {exc}") from exc

    def _spec(
        self, params: OptimizeAllocationIn
    ) -> tuple[ProblemSpec, tuple[DataSource, ...], list[str]]:
        notes: list[str] = []
        sources: tuple[DataSource, ...] = ()
        if params.districts is not None:
            districts = tuple(
                DistrictSpec(
                    district_id=d.district_id,
                    population=float(d.population_affected),
                    severity=d.severity,
                    road_access=d.road_access,
                    alt_delivery_fraction=d.alt_delivery_fraction,
                    cost_multiplier=d.unit_cost_multiplier or 1.0,
                )
                for d in params.districts
            )
            notes.append("districts supplied by the caller; the demo dataset was not used")
        else:
            scenario = self._scenario(params.scenario_id)
            sources = scenario.data_sources
            districts = tuple(
                DistrictSpec(
                    district_id=r.district_id,
                    population=float(r.population),
                    severity=r.default_severity,
                    road_access=r.road_access,
                    alt_delivery_fraction=r.alt_delivery_fraction,
                )
                for r in scenario.districts
            )
            notes.append(
                "demo scenario data: severity and air/boat share are illustrative assumptions, "
                "population is a modelled estimate"
            )
        missing = [c.id for c in params.commodities if c.id not in params.supply]
        if missing:
            notes.append(f"no supply given for {', '.join(sorted(missing))}; treated as 0")
        commodities = tuple(
            CommoditySpec(c.id, c.unit_cost, c.per_person_need, params.supply.get(c.id, 0.0))
            for c in params.commodities
        )
        spec = ProblemSpec(
            districts=districts,
            commodities=commodities,
            budget=params.budget,
            equity_floor=params.equity_floor or 0.0,
            min_road_access=params.min_road_access,
            integer=params.integer,
            on_infeasible_floor=params.on_infeasible_floor,
            solver_time_limit_s=min(params.solver_time_limit_s, MAX_TIME_LIMIT_S),
        )
        return spec, sources, notes

    # ------------------------------------------------------------------ tools

    def optimize_allocation(self, params: OptimizeAllocationIn) -> Outcome[OptimizeAllocationOut]:
        spec, sources, notes = self._spec(params)
        try:
            result = optimize(spec)
        except InvalidProblem as exc:
            raise ToolFailure("INVALID_INPUT", str(exc)) from exc
        except SolverTimeout as exc:
            raise ToolFailure("TIMEOUT", str(exc), retryable=True) from exc
        except SolverError as exc:
            raise ToolFailure("INTERNAL", "solver failed unexpectedly") from exc
        warnings = [*notes, *result.warnings]
        if result.cost_per_person_covered is None:
            warnings.append(
                "no people covered: cost_per_person_covered is reported as 0 because contract "
                "v0.4 has no null for it; do not read it as a cost"
            )
        mode = _used_mode(params)
        if params.districts is None and (params.mode or current_mode()) == "live":
            warnings.insert(0, MODE_FALLBACK_WARNING)
        out = _to_output(result)
        run_id = str(uuid.uuid4())
        self.store.put(run_id, canonical_json(params), out.model_dump_json())
        model = (
            ModelInfo(
                name=f"OR-Tools {result.solver_name}", version=result.solver_version, sha256="n/a"
            )
            if result.solver_name != "none"
            else None
        )
        return Outcome(
            out, warnings=warnings, data_sources=sources, model=model, run_id=run_id, mode=mode
        )

    def sensitivity_report(self, params: SensitivityReportIn) -> Outcome[SensitivityReportOut]:
        stored = self.store.get(params.run_id)
        if stored is None:
            raise ToolFailure("NOT_FOUND", f"run_id {params.run_id!r} is unknown or expired")
        original = OptimizeAllocationIn.model_validate_json(stored.input_json)
        previous = OptimizeAllocationOut.model_validate_json(stored.output_json)
        if previous.status == "infeasible":
            raise ToolFailure(
                "INFEASIBLE",
                "the run was infeasible at the requested floor, so there is no solution to "
                "analyse; re-run with on_infeasible_floor = 'relax'",
            )
        spec, sources, _ = self._spec(original)
        try:
            problem = normalize(spec)
            applied = min(previous.equity.floor_applied, lp_f_max(problem))
            sens = analyze(problem, applied)
            curve = sweep(problem, params.floor_steps, applied)
            priced = {
                s.constraint: s.value
                for s in sens.shadow_prices
                if s.binding and s.value > 0.0 and not s.constraint.startswith(("min_", "equity"))
            }
            ranged = allowable_ranges(problem, applied, priced)
        except InvalidProblem as exc:
            raise ToolFailure("INVALID_INPUT", str(exc)) from exc
        except SolverError as exc:
            raise ToolFailure("INTERNAL", "solver failed unexpectedly") from exc
        notes = [
            *sens.notes,
            "Equity trade-off: LP relaxation re-solved at each floor; floors above f_max "
            f"({curve.f_max:.4g}) are infeasible by the budget and are not solved.",
            "Allowable ranges: for binding supply and budget constraints with a positive "
            "shadow price, the change of the right-hand side over which that shadow price stays "
            "the same (LP relaxation, other constraints and floor bounds fixed, found by "
            "parametric re-solves). Other constraints are not ranged.",
            *(
                [f"Ranges skipped (time budget): {', '.join(ranged.skipped)}."]
                if ranged.skipped
                else []
            ),
        ]
        data = SensitivityReportOut(
            shadow_prices=[
                ShadowPrice(constraint=s.constraint, value=s.value, unit=s.unit, binding=s.binding)
                for s in sens.shadow_prices
            ],
            reduced_costs=[
                ReducedCost(district_id=r.district_id, commodity_id=r.commodity_id, value=r.value)
                for r in sens.reduced_costs
            ],
            ranges=[
                ConstraintRange(
                    constraint=r.constraint,
                    allowable_increase=r.allowable_increase,
                    allowable_decrease=r.allowable_decrease,
                )
                for r in ranged.lines
            ],
            basis="lp_relaxation",
            equity_tradeoff=[
                TradeoffPoint(
                    min_coverage_floor=min(1.0, max(0.0, p.floor)),
                    status="infeasible" if p.status == "infeasible" else "optimal",
                    total_coverage=p.total_coverage,
                    people_covered=p.people_covered,
                )
                for p in curve.points
            ],
            equity_cost=curve.equity_cost,
            notes=notes,
        )
        return Outcome(
            data, warnings=list(curve.warnings), data_sources=sources, mode=_used_mode(original)
        )

    def scenario_districts(self, scenario_id: str) -> list[ScenarioDistrict]:
        scenario = self._scenario(scenario_id)
        return [
            ScenarioDistrict(
                district_id=r.district_id,
                name=r.name,
                population=r.population,
                road_access=r.road_access,
                alt_delivery_fraction=r.alt_delivery_fraction,
                default_severity=r.default_severity,
            )
            for r in scenario.districts
        ]

    # ------------------------------------------------------------------ wiring

    def cores(self) -> dict[str, Callable[[Any], Any]]:
        return {
            "optimize_allocation": self.optimize_allocation,
            "sensitivity_report": self.sensitivity_report,
        }

    def health(self) -> dict[str, bool]:
        """Solver import, dataset loaded, store writable (LED-R8.1)."""
        solvers = all(pywraplp.Solver.CreateSolver(n) is not None for n in ("GLOP", "SCIP"))
        try:
            load_scenario(DEFAULT_SCENARIO, self.demo_root)
            dataset = True
        except (UnknownScenario, DatasetError):
            dataset = False
        return {"solver": solvers, "dataset": dataset, "store": self.store.writable()}


MODE_FALLBACK_WARNING = (
    "MODE_FALLBACK: live mode was requested, but the Ledger has no live data source; "
    "it used the committed demo dataset"
)


def _used_mode(params: OptimizeAllocationIn) -> Mode:
    if params.districts is None:
        return "demo"
    return params.mode or current_mode()


def _to_output(result: Result) -> OptimizeAllocationOut:
    cost_per_person = result.cost_per_person_covered
    return OptimizeAllocationOut(
        status=result.status,
        allocation=[
            AllocationLine(district_id=d, commodity_id=c, quantity=q)
            for d, c, q in result.allocation
        ],
        coverage=[
            CoverageLine(
                district_id=c.district_id,
                fraction=min(1.0, max(0.0, c.fraction)),
                access_mode=c.access_mode,
                unreached_people=c.unreached_people,
            )
            for c in result.coverage
        ],
        equity=Equity(
            floor_requested=result.floor_requested,
            floor_applied=min(result.floor_applied, result.floor_requested),
            max_feasible_floor=result.max_feasible_floor,
        ),
        total_coverage=result.total_coverage,
        total_cost=result.total_cost,
        optimality_gap=result.optimality_gap,
        cost_benefit=CostBenefit(
            cost_per_person_covered=0.0 if cost_per_person is None else cost_per_person,
            people_covered=result.people_covered,
        ),
        solver=SolverInfo(
            name=result.solver_name,
            version=result.solver_version,
            wall_time_s=result.wall_time_s,
        ),
        infeasibility_reason=result.infeasibility_reason,
    )
