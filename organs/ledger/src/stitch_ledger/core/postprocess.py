"""Clamp, repair float error, and compute coverage and cost-benefit (design section 4 step 5).

``evaluate`` is also used by the baseline and by the trade-off sweep, so every coverage number in
the Ledger comes from the same formulas: ``f_dk = min(1, x_dk / R_dk)``,
``cov_d = sum_k lambda_k f_dk``, ``total_coverage = sum_d w_d cov_d`` and
``people_covered = sum_d r_d cov_d``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from stitch_ledger.core.formulate import integer_floor, integer_upper
from stitch_ledger.core.problem import AccessMode, Problem

CLAMP_EPS = 1e-9  # absolute, for float noise in supply and in integer rounding
CLAMP_REL = 1e-12  # relative to the need R_dk, for solver noise in x = R f
Allocation = dict[tuple[int, int], float]


@dataclass(frozen=True)
class Evaluation:
    district_coverage: tuple[float, ...]  # cov_d for every district (0 when not reachable)
    total_coverage: float
    total_cost: float
    people_covered: float

    @property
    def cost_per_person_covered(self) -> float | None:
        return self.total_cost / self.people_covered if self.people_covered > 0 else None


@dataclass(frozen=True)
class DistrictResult:
    district_id: str
    fraction: float
    access_mode: AccessMode
    unreached_people: float


@dataclass(frozen=True)
class Result:
    """Everything ``optimize`` returns. Plain data, no wall-clock fields except ``wall_time_s``."""

    status: str  # optimal | feasible | infeasible
    allocation: tuple[tuple[str, str, float], ...]  # (district_id, commodity_id, quantity)
    coverage: tuple[DistrictResult, ...]
    floor_requested: float
    floor_applied: float
    max_feasible_floor: float
    total_coverage: float
    total_cost: float
    people_covered: float
    cost_per_person_covered: float | None
    optimality_gap: float | None
    solver_name: str
    solver_version: str
    wall_time_s: float
    infeasibility_reason: str | None
    warnings: tuple[str, ...]

    def quantity(self, district_id: str, commodity_id: str) -> float:
        for d, c, q in self.allocation:
            if d == district_id and c == commodity_id:
                return q
        return 0.0


def _upper(problem: Problem, d: int, k: int) -> float:
    r = problem.need[d][k]
    return integer_upper(r) if problem.integer else r


def _units_value(problem: Problem, d: int, k: int) -> float:
    """Coverage value of one unit: ``w_d lambda_k / R_dk`` (= ``s_d lambda_k / n_k``)."""
    r = problem.need[d][k]
    return problem.districts[d].weight * problem.commodities[k].weight / r if r > 0 else 0.0


def cost_of(problem: Problem, x: Allocation) -> float:
    return math.fsum(problem.unit_cost(d, k) * q for (d, k), q in x.items())


def evaluate(problem: Problem, x: Allocation) -> Evaluation:
    ncom = len(problem.commodities)
    cov = [0.0] * len(problem.districts)
    for d in problem.active:
        acc = 0.0
        for k in range(ncom):
            r = problem.need[d][k]
            f = min(1.0, x.get((d, k), 0.0) / r) if r > 0 else 0.0
            acc += problem.commodities[k].weight * f
        cov[d] = min(1.0, acc)
    total = math.fsum(problem.districts[d].weight * cov[d] for d in problem.active)
    people = math.fsum(problem.districts[d].reachable * cov[d] for d in problem.active)
    return Evaluation(tuple(cov), total, cost_of(problem, x), people)


def repair(problem: Problem, raw: Allocation, floor: float = 0.0) -> Allocation:
    """Clamp solver noise, bound by ``U``, round integers, enforce supply and budget exactly.

    Noise is clamped relative to the need (a need of 5e-10 units must not be wiped out by an
    absolute threshold) and never below the equity floor ``floor * share``.
    """
    x: Allocation = {}
    for (d, k), q in raw.items():
        demand = floor * problem.share[d][k]
        if problem.integer:
            q = max(float(round(max(q, 0.0))), integer_floor(floor, problem.share[d][k]))
        elif q < CLAMP_REL * problem.need[d][k]:
            q = demand
        x[d, k] = min(max(q, 0.0), _upper(problem, d, k))
    for k, c in enumerate(problem.commodities):
        keys = [(d, k) for d in problem.active]
        total = math.fsum(x[key] for key in keys)
        if total > c.supply:
            if problem.integer:
                _drop_units(problem, x, keys, total - math.floor(c.supply + CLAMP_EPS), k, floor)
            else:
                factor = c.supply / total
                for key in keys:
                    x[key] *= factor
    if problem.budget is not None:
        cost = cost_of(problem, x)
        if cost > problem.budget:
            if problem.integer:
                _drop_for_budget(problem, x, floor)
            else:
                # Only items that cost something are scaled (their cost is the whole cost), so
                # free goods are never taken away to fix a budget overshoot.
                factor = problem.budget / cost
                for key in x:
                    if problem.unit_cost(*key) > 0.0:
                        x[key] *= factor
    return x


def _spare(problem: Problem, x: Allocation, key: tuple[int, int], floor: float) -> float:
    """Whole units above the integer floor ``ceil(floor * share)`` that can be removed."""
    lb = integer_floor(floor, problem.share[key[0]][key[1]])
    return max(0.0, math.floor(x[key] - lb + CLAMP_EPS))


def _drop_units(
    problem: Problem,
    x: Allocation,
    keys: list[tuple[int, int]],
    excess: float,
    k: int,
    floor: float = 0.0,
) -> None:
    """Integer mode: remove ``excess`` units of commodity k where they are worth least, never
    below the integer floor (the floor plan checked that the floors fit the supply).

    Units are removed from the least valuable district first, in batches: a district's value per
    unit is constant, so one-at-a-time removal would pick the same district until it runs out.
    """
    need = float(math.ceil(excess - CLAMP_EPS))
    order = sorted(keys, key=lambda key: (_units_value(problem, key[0], k), -key[0]))
    for key in order:
        if need <= 0:
            return
        take = min(need, _spare(problem, x, key, floor))
        x[key] -= take
        need -= take


def _drop_for_budget(problem: Problem, x: Allocation, floor: float = 0.0) -> None:
    """Integer mode: remove the least valuable units (per currency unit) until within budget,
    never below the integer floor (found by the Ledger eval: rounding SCIP's solution pushed the
    cost over the budget by float noise and the repair took a unit below the floor). Batched
    like ``_drop_units``; free items are never removed (that cannot lower the cost)."""
    assert problem.budget is not None

    def density(key: tuple[int, int]) -> float:
        return _units_value(problem, *key) / problem.unit_cost(*key)

    paid = [key for key in x if problem.unit_cost(*key) > 0.0]
    over = cost_of(problem, x) - problem.budget
    for key in sorted(paid, key=lambda key: (density(key), key)):
        if over <= 0:
            break
        unit = problem.unit_cost(*key)
        take = min(_spare(problem, x, key, floor), float(math.ceil(over / unit - CLAMP_EPS)))
        x[key] -= take
        over -= take * unit
        if over <= 0:
            # exact check (the running total has float error); one more unit fixes a hair over
            over = cost_of(problem, x) - problem.budget
            if over > 0 and _spare(problem, x, key, floor) >= 1.0:
                x[key] -= 1.0
                over = cost_of(problem, x) - problem.budget


def assemble(
    problem: Problem,
    *,
    status: str,
    x: Allocation,
    floor_requested: float,
    floor_applied: float,
    max_feasible_floor: float,
    optimality_gap: float | None,
    solver_name: str,
    solver_version: str,
    wall_time_s: float,
    infeasibility_reason: str | None,
    warnings: list[str],
) -> Result:
    """Evaluate ``x`` and build the ``Result`` (district lines sorted by id)."""
    ev = evaluate(problem, x)
    lines: list[tuple[str, str, float]] = []
    for d in problem.active:
        for k, c in enumerate(problem.commodities):
            lines.append((problem.districts[d].district_id, c.commodity_id, x.get((d, k), 0.0)))
    coverage = tuple(
        DistrictResult(di.district_id, ev.district_coverage[i], di.access_mode, di.unreached)
        for i, di in enumerate(problem.districts)
    )
    return Result(
        status=status,
        allocation=tuple(lines),
        coverage=coverage,
        floor_requested=floor_requested,
        floor_applied=floor_applied,
        max_feasible_floor=max_feasible_floor,
        total_coverage=ev.total_coverage,
        total_cost=ev.total_cost,
        people_covered=ev.people_covered,
        cost_per_person_covered=ev.cost_per_person_covered,
        optimality_gap=optimality_gap,
        solver_name=solver_name,
        solver_version=solver_version,
        wall_time_s=wall_time_s,
        infeasibility_reason=infeasibility_reason,
        warnings=tuple(warnings),
    )
