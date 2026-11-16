"""LED-P15 (max_feasible_floor is tight) and LED-P19 (relax applies min(requested, max))."""

from __future__ import annotations

from dataclasses import replace

from hypothesis import assume, given, settings
from hypothesis import strategies as st
from ledger_strategies import lp_specs, valid_specs

from stitch_ledger.core.floors import max_feasible_floor, violated_constraint
from stitch_ledger.core.formulate import build
from stitch_ledger.core.optimize import optimize
from stitch_ledger.core.problem import ProblemSpec, normalize
from stitch_ledger.core.solve import solve

EPS = 1e-7


def lp_required_cost(spec: ProblemSpec, phi: float) -> float:
    """Independent cost of delivering ``phi`` times every proportional share."""
    p = normalize(spec)
    return phi * sum(
        p.unit_cost(d, k) * p.share[d][k] for d in p.active for k in range(len(p.commodities))
    )


@settings(deadline=None)
@given(valid_specs(max_districts=6, max_commodities=3, with_budget=True, policy="error"))
def test_p15_floor_is_feasible_at_the_maximum_and_infeasible_just_above(
    spec: ProblemSpec,
) -> None:
    problem = normalize(spec)
    mff, _ = max_feasible_floor(problem)
    at_max = optimize(replace(spec, equity_floor=mff))
    assert at_max.status in ("optimal", "feasible"), at_max.infeasibility_reason
    assert at_max.floor_applied == mff
    shares = {
        (problem.districts[d].district_id, c.commodity_id): problem.share[d][k]
        for d in problem.active
        for k, c in enumerate(problem.commodities)
    }
    for did, cid, q in at_max.allocation:
        assert q >= mff * shares[did, cid] * (1 - EPS) - 1e-9
    if mff < 1.0:
        above = min(1.0, mff + 1e-6)
        over = optimize(replace(spec, equity_floor=above))
        assert over.status == "infeasible" and over.infeasibility_reason
        if spec.integer:
            assert violated_constraint(problem, above) is not None
        else:
            assert lp_required_cost(spec, above) > spec.budget  # type: ignore[operator]


@settings(deadline=None)
@given(lp_specs(max_districts=6, max_commodities=3, with_budget=True))
def test_p15_solver_agrees_with_the_closed_form_on_both_sides(spec: ProblemSpec) -> None:
    """The LP itself is infeasible above the closed-form maximum and feasible at it."""
    problem = normalize(spec)
    mff, _ = max_feasible_floor(problem)
    at = solve(build(problem, mff, integer=False), 10.0)
    assert at.status == "optimal"
    if mff < 1.0:
        above = min(1.0, mff * 1.05 + 1e-3)
        full = lp_required_cost(spec, 1.0)
        assume(full > 0 and (above - mff) * full >= 1e-3)  # violation well above solver tolerance
        assert solve(build(problem, above, integer=False), 10.0).status == "infeasible"


@settings(deadline=None)
@given(valid_specs(max_districts=6, max_commodities=3, with_budget=True, policy="relax"))
def test_p19_relax_applies_the_smaller_of_requested_and_maximum(spec: ProblemSpec) -> None:
    mff, _ = max_feasible_floor(normalize(spec))
    result = optimize(spec)
    assert result.floor_requested == spec.equity_floor
    assert result.floor_applied == min(spec.equity_floor, mff)
    assert result.max_feasible_floor == mff
    relaxed = spec.equity_floor > mff
    assert any("max_feasible_floor" in w for w in result.warnings) == relaxed


@settings(deadline=None)
@given(valid_specs(max_districts=6, max_commodities=3, policy="error"), st.just(0))
def test_error_policy_is_infeasible_exactly_when_the_floor_exceeds_the_maximum(
    spec: ProblemSpec, _: int
) -> None:
    mff, _limiting = max_feasible_floor(normalize(spec))
    result = optimize(spec)
    assert (result.status == "infeasible") == (spec.equity_floor > mff)
    if result.status == "infeasible":
        assert result.infeasibility_reason
