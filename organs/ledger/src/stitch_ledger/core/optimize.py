"""Orchestration of one allocation run (design section 4, ``optimize_allocation`` steps 2 to 5)."""

from __future__ import annotations

import math
import time

from stitch_ledger.core.floors import plan_floor
from stitch_ledger.core.formulate import build
from stitch_ledger.core.postprocess import Allocation, Result, assemble, evaluate, repair
from stitch_ledger.core.problem import Problem, ProblemSpec, normalize, warnings_for
from stitch_ledger.core.solve import SolverError, SolverTimeout, relative_gap, solve

GUARD_TOL = 1e-9
# SCIP stops at a relative gap of 1e-4 by default, so a rounded LP plan may beat an "optimal"
# SCIP plan by that much without anything being wrong. Only a larger shortfall triggers a retry.
GUARD_REL = 1e-3


def _guard_mip(
    problem: Problem,
    floor: float,
    status: str,
    x: Allocation,
    gap: float | None,
    warnings: list[str],
) -> tuple[str, Allocation, float | None]:
    """Check the SCIP plan against the LP plan rounded down to integers (then repaired).

    The rounded plan is integer-feasible, so a SCIP plan worth less is wrong or stopped early.
    Found by the Ledger eval: SCIP reported an all-zero plan as optimal on a problem worth 1.6e6
    (varbound upgrade with needs around 1e7). Then SCIP is re-run without that upgrade within the
    remaining time, and the best of the two plans is returned. The LP optimum is an upper bound
    of the MIP (any MIP plan gives an LP plan ``f = min(1, x / R)`` at least as good), so it
    also bounds the gap of the rounded plan.
    """
    start = time.perf_counter()
    lp_problem = problem.with_integer(False)
    lp_raw = solve(build(lp_problem, floor, integer=False), problem.spec.solver_time_limit_s)
    if lp_raw.status != "optimal" or lp_raw.objective is None:
        return status, x, gap
    rounded = repair(problem, {k: math.floor(v + GUARD_TOL) for k, v in lp_raw.x.items()}, floor)
    mip_value = evaluate(problem, x).total_coverage
    lp_value = lp_raw.objective
    tol = GUARD_REL * max(1.0, lp_value)
    if evaluate(problem, rounded).total_coverage <= mip_value + tol:
        return status, x, gap
    remaining = max(1.0, problem.spec.solver_time_limit_s - (time.perf_counter() - start))
    retry = solve(build(problem, floor, integer=True, no_varbound=True), remaining)
    best_status, best_x, best_gap = "feasible", rounded, None
    if retry.status in ("optimal", "feasible"):
        retry_x = repair(problem, retry.x, floor)
        if evaluate(problem, retry_x).total_coverage >= evaluate(problem, rounded).total_coverage:
            best_status, best_x = retry.status, retry_x
            if retry.status == "optimal":
                best_gap = 0.0
            else:
                assert retry.objective is not None and retry.best_bound is not None
                best_gap = relative_gap(retry.objective, retry.best_bound)
    if best_gap is None:
        best_gap = relative_gap(evaluate(problem, best_x).total_coverage, lp_value)
    warnings.append(
        "the MIP solver's plan was worse than the LP plan rounded to whole units; "
        f"re-solved with safer settings ({best_status})"
    )
    return best_status, best_x, best_gap


def optimize(spec: ProblemSpec) -> Result:
    """Validate, normalise, solve and post-process. Raises ``InvalidProblem``,
    ``SolverTimeout`` or ``SolverError`` for the failure paths of design section 6."""
    problem = normalize(spec)
    return optimize_problem(problem)


def optimize_problem(problem: Problem) -> Result:
    spec = problem.spec
    warnings = warnings_for(problem)
    plan = plan_floor(problem)
    if plan.warning:
        warnings.append(plan.warning)
    common = {
        "floor_requested": plan.requested,
        "max_feasible_floor": plan.max_feasible,
        "warnings": warnings,
    }
    if plan.infeasible:
        return assemble(
            problem,
            status="infeasible",
            x={},
            floor_applied=0.0,
            optimality_gap=None,
            solver_name="none",
            solver_version="",
            wall_time_s=0.0,
            infeasibility_reason=plan.reason,
            **common,  # type: ignore[arg-type]
        )
    name = "SCIP" if problem.integer else "GLOP"
    if not problem.active:
        return assemble(
            problem,
            status="optimal",
            x={},
            floor_applied=plan.applied,
            optimality_gap=0.0,
            solver_name=name,
            solver_version="",
            wall_time_s=0.0,
            infeasibility_reason=None,
            **common,  # type: ignore[arg-type]
        )
    model = build(problem, plan.applied, integer=problem.integer)
    raw = solve(model, spec.solver_time_limit_s)
    if raw.status == "timeout":
        raise SolverTimeout(f"no feasible solution within {spec.solver_time_limit_s:g} s")
    if raw.status not in ("optimal", "feasible"):
        raise SolverError(f"solver returned status {raw.status}")
    x = repair(problem, raw.x, plan.applied)
    status: str = raw.status
    gap: float | None
    if raw.status == "optimal":
        gap = 0.0
    else:
        assert raw.objective is not None and raw.best_bound is not None
        gap = relative_gap(raw.objective, raw.best_bound)
    if problem.integer:
        status, x, gap = _guard_mip(problem, plan.applied, status, x, gap, warnings)
    if status == "feasible" and gap is not None and gap > 0.0:
        warnings.append(f"time limit reached; best incumbent has gap {gap:.3g}")
    return assemble(
        problem,
        status=status,
        x=x,
        floor_applied=plan.applied,
        optimality_gap=gap,
        solver_name=raw.solver_name,
        solver_version=raw.solver_version,
        wall_time_s=raw.wall_time_s,
        infeasibility_reason=None,
        **common,  # type: ignore[arg-type]
    )
