"""Build the OR-Tools model from a ``Problem`` (design 2.3 and 2.4).

LP (GLOP)::

    maximize   sum_d sum_k w_d * lambda_k * f_dk
    s.t.       R_dk f_dk - x_dk <= 0                 (cover)
               x_dk <= U_dk                          (cap; bound on x)
               sum_d x_dk <= S_k                     (supply:<k>)
               sum_dk c_k m_d x_dk <= B              (budget, if given)
               f_dk >= phi * rho_k                   (floor, one row per d,k so duals exist)

MIP (SCIP, ``integer = true``): ``x`` is integer, ``U = ceil(R)`` and the floor is the integer
bound ``x_dk >= ceil(phi * share_dk - 1e-9)``.

Only districts with a positive reachable population get variables (design 2.2 step 6).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ortools.linear_solver import pywraplp

from stitch_ledger.core.problem import Problem

INT_EPS = 1e-9


@dataclass
class Model:
    solver: pywraplp.Solver
    problem: Problem
    floor: float
    integer: bool
    x: dict[tuple[int, int], pywraplp.Variable] = field(default_factory=dict)
    f: dict[tuple[int, int], pywraplp.Variable] = field(default_factory=dict)
    supply_rows: dict[int, pywraplp.Constraint] = field(default_factory=dict)
    budget_row: pywraplp.Constraint | None = None
    floor_rows: dict[tuple[int, int], pywraplp.Constraint] = field(default_factory=dict)
    cover_rows: dict[tuple[int, int], pywraplp.Constraint] = field(default_factory=dict)


def integer_upper(need: float) -> float:
    """``U = ceil(R)`` for integer mode, ignoring float noise of 1e-9."""
    return float(math.ceil(need - INT_EPS))


def integer_floor(phi: float, share: float) -> float:
    """Integer floor ``ceil(phi * share - 1e-9)``, never negative."""
    return float(max(0, math.ceil(phi * share - INT_EPS)))


def build(problem: Problem, floor: float, *, integer: bool, floor_rows: bool = True) -> Model:
    """Build the model at the given (already feasible) equity floor.

    ``floor_rows`` keeps explicit floor rows in LP mode even when ``floor = 0`` (needed by the
    sensitivity report to read floor duals).
    """
    solver = pywraplp.Solver.CreateSolver("SCIP" if integer else "GLOP")
    if solver is None:  # pragma: no cover - the ortools wheel ships both
        raise RuntimeError("OR-Tools solver backend unavailable")
    solver.SetNumThreads(1)
    if integer:
        solver.SetSolverSpecificParametersAsString(
            "randomization/randomseedshift = 0\n"
            "randomization/permutationseed = 0\n"
            "randomization/lpseed = 0\n"
        )
    inf = solver.infinity()
    m = Model(solver=solver, problem=problem, floor=floor, integer=integer)
    ncom = len(problem.commodities)
    obj = solver.Objective()
    for d in problem.active:
        di = problem.districts[d]
        for k in range(ncom):
            r = problem.need[d][k]
            name = f"{d}_{k}"
            if integer:
                lb = integer_floor(floor, problem.share[d][k])
                ub = max(lb, integer_upper(r))
                x = solver.IntVar(lb, ub, f"x_{name}")
            else:
                x = solver.NumVar(0.0, r, f"x_{name}")
            f = solver.NumVar(0.0, 1.0, f"f_{name}")
            m.x[d, k] = x
            m.f[d, k] = f
            cover = solver.Constraint(-inf, 0.0, f"cover_{name}")
            cover.SetCoefficient(f, r)
            cover.SetCoefficient(x, -1.0)
            m.cover_rows[d, k] = cover
            obj.SetCoefficient(f, di.weight * problem.commodities[k].weight)
            if not integer and floor_rows:
                rho = problem.commodities[k].supply_ratio
                row = solver.Constraint(floor * rho, inf, f"floor_{name}")
                row.SetCoefficient(f, 1.0)
                m.floor_rows[d, k] = row
    obj.SetMaximization()
    for k, c in enumerate(problem.commodities):
        row = solver.Constraint(-inf, c.supply, f"supply_{k}")
        for d in problem.active:
            row.SetCoefficient(m.x[d, k], 1.0)
        m.supply_rows[k] = row
    if problem.budget is not None:
        row = solver.Constraint(-inf, problem.budget, "budget")
        for d in problem.active:
            for k in range(ncom):
                row.SetCoefficient(m.x[d, k], problem.unit_cost(d, k))
        m.budget_row = row
    return m
