"""Equity trade-off: coverage as a function of the equity floor (LED-R10).

Floors are ``linspace(0, 1, floor_steps)`` plus ``f_max``, sorted and de-duplicated. Floors at or
below ``f_max`` are LP re-solves (the LP relaxation, whatever the original run used, so
``basis = "lp_relaxation"``). Floors above ``f_max`` are reported ``infeasible`` with null values
and are never solved: in the LP the floor is infeasible exactly when it exceeds
``f_max = min(1, B / full_floor_cost)``, so the tail is analytic (design 2.5).

The sweep has a time budget (default 10 s). When it runs out, the points solved so far are kept,
the infeasible tail (which needs no solve) is still reported, and a warning names the floors that
were skipped.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from stitch_ledger.core.floors import max_feasible_floor
from stitch_ledger.core.lp import solve_relaxation
from stitch_ledger.core.problem import Problem

DEFAULT_BUDGET_S = 10.0
MERGE_TOL = 1e-12
Clock = Callable[[], float]


@dataclass(frozen=True)
class TradeoffPoint:
    floor: float
    status: str  # "optimal" | "infeasible"
    total_coverage: float | None
    people_covered: float | None


@dataclass(frozen=True)
class Tradeoff:
    points: tuple[TradeoffPoint, ...]
    f_max: float
    equity_cost: float | None
    warnings: tuple[str, ...]
    solves: int


def grid(steps: int, f_max: float) -> list[float]:
    """``steps`` equally spaced floors in [0, 1] plus ``f_max``, sorted and de-duplicated."""
    pts = [i / (steps - 1) for i in range(steps)] + [f_max]
    out: list[float] = []
    for p in sorted(pts):
        if not out or p - out[-1] > MERGE_TOL:
            out.append(p)
    return out


def lp_f_max(problem: Problem) -> float:
    """Largest feasible uniform floor of the LP relaxation."""
    return max_feasible_floor(problem.with_integer(False))[0]


def sweep(
    problem: Problem,
    steps: int,
    applied_floor: float,
    *,
    budget_s: float = DEFAULT_BUDGET_S,
    clock: Clock = time.monotonic,
) -> Tradeoff:
    """Trade-off curve and ``equity_cost`` for a run that applied ``applied_floor``."""
    f_max = lp_f_max(problem)
    floors = grid(steps, f_max)
    start = clock()
    solved: dict[float, TradeoffPoint] = {}
    skipped: list[float] = []
    solves = 0

    def solve_at(phi: float) -> TradeoffPoint:
        nonlocal solves
        rel = solve_relaxation(problem, min(phi, f_max))
        solves += 1
        return TradeoffPoint(
            phi, "optimal", rel.evaluation.total_coverage, rel.evaluation.people_covered
        )

    points: list[TradeoffPoint] = []
    for phi in floors:
        if phi > f_max + MERGE_TOL:
            points.append(TradeoffPoint(phi, "infeasible", None, None))
        elif clock() - start > budget_s:
            skipped.append(phi)
        else:
            point = solve_at(phi)
            solved[phi] = point
            points.append(point)
    warnings: list[str] = []
    if skipped:
        shown = ", ".join(f"{p:.3g}" for p in skipped)
        warnings.append(
            f"equity trade-off stopped after {budget_s:g} s; floors not computed: {shown}"
        )

    equity_cost: float | None = None
    if applied_floor > 0.0:
        base = solved.get(0.0)
        at_applied = next(
            (p for p in solved.values() if abs(p.floor - applied_floor) <= MERGE_TOL), None
        )
        if base is None and clock() - start <= budget_s:
            base = solve_at(0.0)
        if at_applied is None and clock() - start <= budget_s:
            at_applied = solve_at(applied_floor)
        if base is not None and at_applied is not None:
            assert base.total_coverage is not None and at_applied.total_coverage is not None
            equity_cost = max(0.0, base.total_coverage - at_applied.total_coverage)
        else:
            warnings.append("equity_cost not computed within the time budget")
    return Tradeoff(tuple(points), f_max, equity_cost, tuple(warnings), solves)
