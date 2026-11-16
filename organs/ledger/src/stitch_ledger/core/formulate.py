"""Build the OR-Tools model from a ``Problem`` (design 2.3 and 2.4).

Design model (``x`` units delivered, ``f`` coverage fraction)::

    maximize   sum_d sum_k w_d * lambda_k * f_dk
    s.t.       R_dk f_dk <= x_dk <= U_dk
               sum_d x_dk <= S_k                     (supply:<k>)
               sum_dk c_k m_d x_dk <= B              (budget, if given)
               f_dk >= phi * rho_k                   (equity floor)

LP (GLOP). Since ``x`` only appears in ``R f <= x``, in the supply row and in the budget row,
and a smaller ``x`` is never worse, the LP is solved in the substituted form ``x = R f`` (U = R)::

    maximize   sum w_d lambda_k f_dk
    s.t.       sum_d R_dk f_dk <= S_k,   sum_dk c_k m_d R_dk f_dk <= B,   phi rho_k <= f_dk <= 1

This is the same feasible set and objective in different variables. It is scale free (every
variable is in [0, 1] whatever the size of ``R``) and the floor is an exact variable bound.
The floor dual of the design (row ``f >= phi rho``) is the reduced cost of ``f`` at its bound.
The property tests showed the original form misbehaves when needs are tiny or floors are tiny
(absolute solver tolerances), see ``docs/ledger-model.md``.

MIP (SCIP, ``integer = true``): ``x`` is integer in ``[ceil(phi share - 1e-9), ceil(R)]`` and
``f`` is tied to it by ``R f <= x``.

Only districts with a positive reachable population get variables (design 2.2 step 6).
The objective is divided by its largest coefficient (``Model.objective_scale``) and coefficients
below ``1e-12`` of it are dropped: GLOP returns ``ABNORMAL`` for coefficients near the subnormal
range (severity 1e-308) and the relative effect of the drop is below 1e-12.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ortools.linear_solver import pywraplp

from stitch_ledger.core.problem import Problem

INT_EPS = 1e-9
OBJ_DROP = 1e-12
ROW_DROP = 1e-13


@dataclass
class Model:
    solver: pywraplp.Solver
    problem: Problem
    floor: float
    integer: bool
    f: dict[tuple[int, int], pywraplp.Variable] = field(default_factory=dict)
    x: dict[tuple[int, int], pywraplp.Variable] = field(default_factory=dict)  # MIP only
    supply_rows: dict[int, pywraplp.Constraint] = field(default_factory=dict)
    budget_row: pywraplp.Constraint | None = None
    objective_scale: float = 1.0
    supply_scale: dict[int, float] = field(default_factory=dict)  # row k divided by this
    budget_scale: float = 1.0


def integer_upper(need: float) -> float:
    """``U = ceil(R)`` for integer mode, ignoring float noise of 1e-9."""
    return float(max(0, math.ceil(need - INT_EPS)))


def integer_floor(phi: float, share: float) -> float:
    """Integer floor ``ceil(phi * share - 1e-9)``, never negative."""
    return float(max(0, math.ceil(phi * share - INT_EPS)))


def build(problem: Problem, floor: float, *, integer: bool) -> Model:
    """Build the model at the given (already feasible) equity floor."""
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
    top = max(
        (
            problem.districts[d].weight * problem.commodities[k].weight
            for d in problem.active
            for k in range(ncom)
        ),
        default=0.0,
    )
    m.objective_scale = top if top > 0.0 else 1.0
    obj = solver.Objective()
    for d in problem.active:
        di = problem.districts[d]
        for k in range(ncom):
            r = problem.need[d][k]
            name = f"{d}_{k}"
            if integer:
                lb = integer_floor(floor, problem.share[d][k])
                x = solver.IntVar(lb, max(lb, integer_upper(r)), f"x_{name}")
                f = solver.NumVar(0.0, 1.0, f"f_{name}")
                m.x[d, k] = x
                cover = solver.Constraint(-inf, 0.0, f"cover_{name}")
                cover.SetCoefficient(f, r)
                cover.SetCoefficient(x, -1.0)
            else:
                lo = min(1.0, floor * problem.commodities[k].supply_ratio)
                f = solver.NumVar(lo, 1.0, f"f_{name}")
            m.f[d, k] = f
            coef = di.weight * problem.commodities[k].weight / m.objective_scale
            obj.SetCoefficient(f, coef if coef >= OBJ_DROP else 0.0)
    obj.SetMaximization()
    for k, c in enumerate(problem.commodities):
        if integer:
            coefs = {d: 1.0 for d in problem.active}
        else:
            coefs = {d: problem.need[d][k] for d in problem.active}
        scale = max(coefs.values(), default=0.0)
        m.supply_scale[k] = scale if scale > 0.0 else 1.0
        # sum_d coef_d * var_d can never exceed sum_d coef_d (vars are within [0, 1] in LP mode),
        # so capping the limit there keeps the feasible set and keeps the RHS bounded.
        limit = c.supply if integer else min(c.supply, math.fsum(coefs.values()))
        row = solver.Constraint(-inf, limit / m.supply_scale[k], f"supply_{k}")
        for d in problem.active:
            rel = coefs[d] / m.supply_scale[k]
            if rel >= ROW_DROP:
                row.SetCoefficient(m.x[d, k] if integer else m.f[d, k], rel)
        m.supply_rows[k] = row
    if problem.budget is not None:
        cost_coefs = {
            (d, k): problem.unit_cost(d, k) * (1.0 if integer else problem.need[d][k])
            for d in problem.active
            for k in range(ncom)
        }
        scale = max(cost_coefs.values(), default=0.0)
        if scale > 0.0:
            m.budget_scale = scale
            limit = problem.budget
            if not integer:
                limit = min(limit, math.fsum(cost_coefs.values()))
            row = solver.Constraint(-inf, limit / scale, "budget")
            for (d, k), coef in cost_coefs.items():
                if coef / scale >= ROW_DROP:
                    row.SetCoefficient(m.x[d, k] if integer else m.f[d, k], coef / scale)
            m.budget_row = row
    return m
