"""LED-P20 (task 16): on its allowable range a shadow price is exact. With no floor, moving a
supply or the budget to either end of its range changes the optimum (solved independently by
``optimize``) by exactly shadow price x change; ranges are non-negative and a decrease never
exceeds the right-hand side."""

from __future__ import annotations

import dataclasses

from hypothesis import given, settings
from ledger_strategies import lp_specs, objective_scale

from stitch_ledger.core.optimize import optimize
from stitch_ledger.core.problem import ProblemSpec, normalize
from stitch_ledger.core.ranges import allowable_ranges
from stitch_ledger.core.sensitivity import analyze

REL = 1e-6


def _with_rhs(spec: ProblemSpec, name: str, rhs: float) -> ProblemSpec:
    if name == "budget":
        return dataclasses.replace(spec, budget=rhs)
    cid = name.split(":", 1)[1]
    commodities = tuple(
        dataclasses.replace(c, supply=rhs) if c.commodity_id == cid else c for c in spec.commodities
    )
    return dataclasses.replace(spec, commodities=commodities)


def _rhs(spec: ProblemSpec, name: str) -> float:
    if name == "budget":
        assert spec.budget is not None
        return spec.budget
    cid = name.split(":", 1)[1]
    return next(c.supply for c in spec.commodities if c.commodity_id == cid)


@settings(deadline=None)
@given(lp_specs(max_districts=6, with_floor=False))
def test_p20_shadow_price_is_exact_on_its_range(spec: ProblemSpec) -> None:
    problem = normalize(spec)
    sens = analyze(problem, 0.0)
    priced = {
        s.constraint: s.value
        for s in sens.shadow_prices
        if s.binding and s.value > 0 and s.constraint.startswith(("supply", "budget"))
    }
    ranges = allowable_ranges(problem, 0.0, priced)
    assert not ranges.skipped
    v0 = optimize(spec).total_coverage
    tol = REL * objective_scale(problem)
    for line in ranges.lines:
        b, y = _rhs(spec, line.constraint), priced[line.constraint]
        assert line.allowable_increase >= 0.0
        assert 0.0 <= line.allowable_decrease <= b * (1 + 1e-12)
        up = optimize(_with_rhs(spec, line.constraint, b + line.allowable_increase))
        assert abs(up.total_coverage - (v0 + y * line.allowable_increase)) <= tol, line
        lo_rhs = max(0.0, b - line.allowable_decrease)
        down = optimize(_with_rhs(spec, line.constraint, lo_rhs))
        assert abs(down.total_coverage - (v0 - y * (b - lo_rhs))) <= tol, line
