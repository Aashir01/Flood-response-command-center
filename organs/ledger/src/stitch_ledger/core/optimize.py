"""Orchestration of one allocation run (design section 4, ``optimize_allocation`` steps 2 to 5)."""

from __future__ import annotations

from stitch_ledger.core.floors import plan_floor
from stitch_ledger.core.formulate import build
from stitch_ledger.core.postprocess import Result, assemble, repair
from stitch_ledger.core.problem import Problem, ProblemSpec, normalize, warnings_for
from stitch_ledger.core.solve import SolverError, SolverTimeout, relative_gap, solve


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
    x = repair(problem, raw.x)
    gap: float | None
    if raw.status == "optimal":
        gap = 0.0
    else:
        assert raw.objective is not None and raw.best_bound is not None
        gap = relative_gap(raw.objective, raw.best_bound)
        warnings.append(f"time limit reached; best incumbent has gap {gap:.3g}")
    return assemble(
        problem,
        status=raw.status,
        x=x,
        floor_applied=plan.applied,
        optimality_gap=gap,
        solver_name=raw.solver_name,
        solver_version=raw.solver_version,
        wall_time_s=raw.wall_time_s,
        infeasibility_reason=None,
        **common,  # type: ignore[arg-type]
    )
