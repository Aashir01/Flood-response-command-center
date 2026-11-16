"""Solve the LP relaxation of a problem at a given equity floor.

Shared by ``sensitivity`` (duals) and ``tradeoff`` (equity sweep). Shadow prices and the trade-off
curve always come from the LP relaxation (design section 4, ``sensitivity_report``), also when
the original run used integers.
"""

from __future__ import annotations

from dataclasses import dataclass

from stitch_ledger.core.formulate import Model, build
from stitch_ledger.core.postprocess import Allocation, Evaluation, evaluate, repair
from stitch_ledger.core.problem import Problem
from stitch_ledger.core.solve import RawSolution, SolverError, solve

LP_TIME_LIMIT_S = 30.0


@dataclass(frozen=True)
class Relaxation:
    model: Model
    raw: RawSolution
    x: Allocation  # repaired (supply and budget exact), same as an allocation solve
    evaluation: Evaluation


def solve_relaxation(problem: Problem, floor: float) -> Relaxation:
    """Build and solve the LP at ``floor`` (which must be at most ``max_feasible_floor``)."""
    lp = problem.with_integer(False)
    model = build(lp, floor, integer=False)
    raw = solve(model, LP_TIME_LIMIT_S)
    if raw.status != "optimal":
        raise SolverError(f"LP relaxation returned status {raw.status} at floor {floor:.6g}")
    x = repair(lp, raw.x, floor)
    return Relaxation(model, raw, x, evaluate(lp, x))
