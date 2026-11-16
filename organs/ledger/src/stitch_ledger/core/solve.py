"""Run GLOP (LP) or SCIP (MIP) on a built model and return the raw solution."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from ortools.linear_solver import pywraplp

from stitch_ledger.core.formulate import Model

RawStatus = Literal["optimal", "feasible", "infeasible", "timeout", "error"]


@dataclass(frozen=True)
class RawSolution:
    status: RawStatus
    x: dict[tuple[int, int], float]
    objective: float | None
    best_bound: float | None
    solver_name: str
    solver_version: str
    wall_time_s: float


def solve(model: Model, time_limit_s: float) -> RawSolution:
    """Solve ``model``. LP is solved to optimality; MIP honours ``time_limit_s``."""
    solver = model.solver
    if model.integer:
        solver.SetTimeLimit(max(1, int(time_limit_s * 1000)))
    start = time.perf_counter()
    code = solver.Solve()
    wall = time.perf_counter() - start
    name = "SCIP" if model.integer else "GLOP"
    version = str(solver.SolverVersion())
    status: RawStatus
    if code == pywraplp.Solver.OPTIMAL:
        status = "optimal"
    elif code == pywraplp.Solver.FEASIBLE:
        status = "feasible"
    elif code == pywraplp.Solver.INFEASIBLE:
        status = "infeasible"
    elif code == pywraplp.Solver.NOT_SOLVED and model.integer and wall >= time_limit_s * 0.9:
        status = "timeout"
    else:
        status = "error"
    if status in ("optimal", "feasible"):
        x = {key: var.solution_value() for key, var in model.x.items()}
        objective = float(solver.Objective().Value())
        bound = float(solver.Objective().BestBound()) if model.integer else objective
    else:
        x, objective, bound = {}, None, None
    return RawSolution(status, x, objective, bound, name, version, wall)


def relative_gap(objective: float, bound: float) -> float:
    """Relative optimality gap of a maximisation incumbent, never negative."""
    return max(0.0, (bound - objective) / max(abs(objective), 1e-9))


class SolverTimeout(RuntimeError):
    """The time limit passed with no incumbent (maps to `TIMEOUT`, retryable)."""


class SolverError(RuntimeError):
    """The solver returned an unexpected status (maps to `INTERNAL`)."""
