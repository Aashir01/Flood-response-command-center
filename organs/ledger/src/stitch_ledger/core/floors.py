"""Highest feasible equity floor and the relax/error policy (design 2.5 and section 4 step 3).

LP: supply never makes a floor infeasible (the floor demand for commodity k is
``phi * min(S_k, sum_d R_dk) <= S_k``), only the budget can, so
``max_feasible_floor = min(1, B / sum_dk c_k m_d share_dk)``.

MIP: the floor is ``x_dk >= ceil(phi * share_dk - 1e-9)``. Feasibility (supply per commodity and
the budget) is monotone in ``phi``, so the maximum is found by bisection (40 steps, arithmetic
only, no solver).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from stitch_ledger.core.formulate import integer_floor
from stitch_ledger.core.problem import Problem

BISECTION_STEPS = 40
BUDGET_TOL = 1e-9


@dataclass(frozen=True)
class FloorPlan:
    requested: float
    max_feasible: float
    applied: float
    limiting_constraint: str | None  # "budget" or "supply:<k>" when max_feasible < 1
    infeasible: bool = False
    reason: str | None = None
    warning: str | None = None


def _full_floor_cost(problem: Problem) -> float:
    return sum(
        problem.unit_cost(d, k) * problem.share[d][k]
        for d in problem.active
        for k in range(len(problem.commodities))
    )


def _lp_max_floor(problem: Problem) -> tuple[float, str | None]:
    if problem.budget is None:
        return 1.0, None
    cost = _full_floor_cost(problem)
    if cost <= 0.0:
        return 1.0, None
    ratio = problem.budget / cost
    return (ratio, "budget") if ratio < 1.0 else (1.0, None)


def violated_constraint(problem: Problem, phi: float) -> str | None:
    """Integer mode: the first constraint the floor ``phi`` breaks, or None if it is feasible."""
    cost = 0.0
    for k, c in enumerate(problem.commodities):
        total = 0.0
        for d in problem.active:
            units = integer_floor(phi, problem.share[d][k])
            total += units
            cost += units * problem.unit_cost(d, k)
        if total > math.floor(c.supply + 1e-9):
            return f"supply:{c.commodity_id}"
    if problem.budget is not None and cost > problem.budget + BUDGET_TOL * max(1.0, problem.budget):
        return "budget"
    return None


def _mip_max_floor(problem: Problem) -> tuple[float, str | None]:
    if violated_constraint(problem, 1.0) is None:
        return 1.0, None
    lo, hi = 0.0, 1.0  # lo is feasible (phi = 0 demands nothing), hi is not
    for _ in range(BISECTION_STEPS):
        mid = (lo + hi) / 2.0
        if violated_constraint(problem, mid) is None:
            lo = mid
        else:
            hi = mid
    return lo, violated_constraint(problem, hi)


def max_feasible_floor(problem: Problem) -> tuple[float, str | None]:
    """Return ``(value, limiting_constraint)``. The constraint is None when the value is 1."""
    value, limiting = _mip_max_floor(problem) if problem.integer else _lp_max_floor(problem)
    return min(1.0, max(0.0, value)), limiting


def plan_floor(problem: Problem) -> FloorPlan:
    """Apply the relax/error policy to the requested floor (LED-R3.2 to R3.4, LED-P19)."""
    requested = problem.spec.equity_floor
    mff, limiting = max_feasible_floor(problem)
    if requested <= mff:
        return FloorPlan(requested, mff, requested, limiting)
    what = limiting or "budget"
    if problem.spec.on_infeasible_floor == "error":
        reason = (
            f"equity_floor {requested:.4g} is infeasible: constraint {what} allows at most "
            f"{mff:.4g} (max_feasible_floor)"
        )
        return FloorPlan(requested, mff, 0.0, limiting, infeasible=True, reason=reason)
    warning = (
        f"equity_floor {requested:.4g} is not feasible (limited by {what}); "
        f"solved at max_feasible_floor {mff:.4g}"
    )
    return FloorPlan(requested, mff, mff, limiting, warning=warning)
