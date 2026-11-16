"""Shadow prices, reduced costs and binding flags from the LP relaxation (LED-R6).

The LP is the substituted form of ``formulate`` (variables ``f_dk`` in ``[phi rho_k, 1]``,
objective divided by ``objective_scale``, rows divided by their scales). A dual of a scaled row
is converted back with the chain rule::

    d objective / d rhs   =  dual_scaled * objective_scale / row_scale

Meaning of each number (objective = coverage-weighted people, ``sum_d w_d cov_d``):

* ``supply:<k>``: extra coverage-weighted people per extra unit of commodity k. Never negative.
* ``budget``: per extra currency unit. Never negative.
* ``min_coverage:<d>``: sum over commodities of the reduced cost of ``f_dk`` where it sits at
  its floor, i.e. coverage lost per unit of extra floor on district d. Never positive.
* ``equity_floor``: the same summed over all districts and multiplied by ``rho_k``, i.e. the
  derivative with respect to the uniform floor ``phi``: coverage lost per unit of ``phi``.

A constraint is ``binding`` when its slack is within solver tolerance of zero. A non-binding
constraint has a shadow price of exactly 0 (LED-P6). Supply that is at least the total need is
reported as not scarce: one more unit cannot raise coverage because ``f <= 1``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from stitch_ledger.core.lp import Relaxation, solve_relaxation
from stitch_ledger.core.problem import Problem

BIND_TOL = 1e-7  # relative; solver feasibility tolerance is about 1e-8 on scaled rows
DUAL_ZERO = 1e-9


@dataclass(frozen=True)
class ShadowLine:
    constraint: str
    value: float
    unit: str
    binding: bool


@dataclass(frozen=True)
class ReducedCostLine:
    district_id: str
    commodity_id: str
    value: float


@dataclass(frozen=True)
class Sensitivity:
    floor: float
    shadow_prices: tuple[ShadowLine, ...]
    reduced_costs: tuple[ReducedCostLine, ...]
    total_coverage: float
    people_covered: float
    notes: tuple[str, ...]


def _clean(value: float) -> float:
    return 0.0 if abs(value) <= DUAL_ZERO else value


def analyze(problem: Problem, floor: float, relaxation: Relaxation | None = None) -> Sensitivity:
    """Duals of the LP relaxation at ``floor`` (the floor actually applied by the run)."""
    rel = relaxation or solve_relaxation(problem, floor)
    model = rel.model
    scale = model.objective_scale
    lines: list[ShadowLine] = []
    for k, c in enumerate(problem.commodities):
        used = math.fsum(rel.x.get((d, k), 0.0) for d in problem.active)
        binding = c.supply - used <= BIND_TOL * max(1.0, c.supply)
        scarce = c.supply < c.total_need * (1.0 - 1e-12)
        value = 0.0
        if binding and scarce and problem.active:
            raw = model.supply_rows[k].dual_value() * scale / model.supply_scale[k]
            value = max(0.0, _clean(raw))
        lines.append(
            ShadowLine(
                f"supply:{c.commodity_id}",
                value,
                f"coverage-weighted people per unit of {c.commodity_id}",
                binding,
            )
        )
    if problem.budget is not None:
        cost = math.fsum(problem.unit_cost(d, k) * q for (d, k), q in rel.x.items())
        binding = problem.budget - cost <= BIND_TOL * max(1.0, problem.budget)
        value = 0.0
        if binding and model.budget_row is not None:
            raw = model.budget_row.dual_value() * scale / model.budget_scale
            value = max(0.0, _clean(raw))
        lines.append(
            ShadowLine("budget", value, "coverage-weighted people per currency unit", binding)
        )

    ncom = len(problem.commodities)
    floor_by_district: dict[int, float] = {}
    floor_bound: dict[int, bool] = {}
    aggregate = 0.0
    reduced: list[ReducedCostLine] = []
    for d in problem.active:
        total = 0.0
        at_floor = False
        for k in range(ncom):
            need = problem.need[d][k]
            var = model.f[d, k]
            rc = var.reduced_cost() * scale
            if need > 0.0:
                reduced.append(
                    ReducedCostLine(
                        problem.districts[d].district_id,
                        problem.commodities[k].commodity_id,
                        _clean(rc / need),
                    )
                )
            lo = min(1.0, floor * problem.commodities[k].supply_ratio)
            if floor > 0.0 and lo > 0.0 and abs(var.solution_value() - lo) <= 1e-9 * max(1.0, lo):
                at_floor = True
                pull = min(0.0, _clean(rc))
                total += pull
                aggregate += pull * problem.commodities[k].supply_ratio
        floor_by_district[d] = total
        floor_bound[d] = at_floor
    if floor > 0.0:
        for d in problem.active:
            lines.append(
                ShadowLine(
                    f"min_coverage:{problem.districts[d].district_id}",
                    _clean(floor_by_district[d]),
                    "coverage-weighted people per unit of district floor",
                    floor_bound[d],
                )
            )
    lines.append(
        ShadowLine(
            "equity_floor",
            _clean(aggregate) if floor > 0.0 else 0.0,
            "coverage-weighted people per unit of equity floor",
            floor > 0.0 and any(floor_bound.values()),
        )
    )
    notes = [
        "Shadow prices come from the LP relaxation at the applied equity floor "
        f"({floor:.4g}); with integer = true they are approximations of the integer problem.",
        "Reduced costs are per unit of commodity: positive at full coverage (an extra unit would "
        "have been worth that much), negative at the floor or at zero (a unit sent there costs "
        "that much objective).",
    ]
    return Sensitivity(
        floor=floor,
        shadow_prices=tuple(lines),
        reduced_costs=tuple(reduced),
        total_coverage=rel.evaluation.total_coverage,
        people_covered=rel.evaluation.people_covered,
        notes=tuple(notes),
    )
