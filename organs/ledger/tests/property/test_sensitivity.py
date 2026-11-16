"""LED-P6: non-binding duals are zero, supply and budget duals are >= 0, floor duals are <= 0."""

from __future__ import annotations

from hypothesis import given, settings
from ledger_strategies import valid_specs

from stitch_ledger.core.floors import plan_floor
from stitch_ledger.core.problem import ProblemSpec, normalize
from stitch_ledger.core.sensitivity import analyze

TOL = 1e-9


def _check(spec: ProblemSpec) -> None:
    problem = normalize(spec)
    plan = plan_floor(problem)
    if plan.infeasible:
        return
    s = analyze(problem, plan.applied)
    names = [p.constraint for p in s.shadow_prices]
    assert len(names) == len(set(names))
    assert {f"supply:{c.commodity_id}" for c in problem.commodities} <= set(names)
    assert ("budget" in names) == (spec.budget is not None)
    assert "equity_floor" in names
    for p in s.shadow_prices:
        if not p.binding:
            assert abs(p.value) <= TOL, p
        if p.constraint.startswith("supply:") or p.constraint == "budget":
            assert p.value >= -TOL, p
        else:
            assert p.value <= TOL, p
    if plan.applied == 0.0:
        assert all(
            p.value == 0.0 and not p.binding
            for p in s.shadow_prices
            if p.constraint == "equity_floor"
        )


@settings(deadline=None)
@given(valid_specs(integer=False, max_districts=8, max_commodities=3))
def test_p6_dual_signs_and_complementary_slackness_lp(spec: ProblemSpec) -> None:
    _check(spec)


@settings(deadline=None)
@given(valid_specs(integer=True, max_districts=6, max_commodities=3))
def test_p6_holds_for_the_lp_relaxation_of_integer_runs(spec: ProblemSpec) -> None:
    _check(spec)
