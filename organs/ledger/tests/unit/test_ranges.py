"""Allowable ranges by parametric re-solve (LED-R6.3, ledger task 16), against hand-solved cases.

Instance: districts A (100 people, severity 1) and B (100 people, severity 0.5), both full road
access, one commodity with need 1 per person, no floor. The LP fills A first (1 coverage per
unit), then B (0.5 per unit). So V(S) = S for S <= 100, 100 + 0.5 (S - 100) up to 200, then flat.
"""

from __future__ import annotations

import pytest

from stitch_ledger.core.problem import CommoditySpec, DistrictSpec, ProblemSpec, normalize
from stitch_ledger.core.ranges import allowable_ranges
from stitch_ledger.core.sensitivity import analyze

A = DistrictSpec("a", 100.0, 1.0, 1.0)
B = DistrictSpec("b", 100.0, 0.5, 1.0)


def _ranges(spec: ProblemSpec) -> dict[str, tuple[float, float, float]]:
    problem = normalize(spec)
    sens = analyze(problem, spec.equity_floor)
    priced = {
        s.constraint: s.value
        for s in sens.shadow_prices
        if s.binding and s.value > 0 and s.constraint.startswith(("supply", "budget"))
    }
    r = allowable_ranges(problem, spec.equity_floor, priced)
    return {
        line.constraint: (priced[line.constraint], line.allowable_increase, line.allowable_decrease)
        for line in r.lines
    }


@pytest.mark.parametrize(
    ("supply", "dual", "inc", "dec"),
    [(50.0, 1.0, 50.0, 50.0), (150.0, 0.5, 50.0, 50.0), (120.0, 0.5, 80.0, 20.0)],
)
def test_supply_range_hand_solved(supply: float, dual: float, inc: float, dec: float) -> None:
    spec = ProblemSpec(districts=(A, B), commodities=(CommoditySpec("food", 1.0, 1.0, supply),))
    got = _ranges(spec)["supply:food"]
    assert got == pytest.approx((dual, inc, dec), rel=1e-6)


def test_budget_range_hand_solved() -> None:
    """Unit cost 2, budget 60, plenty of supply: 30 units go to A, dual 1/2 per currency unit.
    The price holds while the budget buys units for A: from 0 up to 200 (100 units)."""
    spec = ProblemSpec(
        districts=(A, B), commodities=(CommoditySpec("food", 2.0, 1.0, 1000.0),), budget=60.0
    )
    got = _ranges(spec)
    assert "supply:food" not in got
    assert got["budget"] == pytest.approx((0.5, 140.0, 60.0), rel=1e-6)


def test_floor_bounds_limit_the_decrease() -> None:
    """Floor 0.5, supply 50: rho = 0.25, so the fixed floor bounds are 12.5 units each (25 in
    all) and the other 25 go to A (dual 1). The price holds down to the 25 the floors use
    (decrease 25) and up to A being full at 100 + 12.5 = 112.5 (increase 62.5)."""
    spec = ProblemSpec(
        districts=(A, B),
        commodities=(CommoditySpec("food", 1.0, 1.0, 50.0),),
        equity_floor=0.5,
    )
    got = _ranges(spec)["supply:food"]
    dual, inc, dec = got
    assert dual == pytest.approx(1.0)
    assert dec == pytest.approx(25.0, abs=1e-6)
    assert inc == pytest.approx(62.5, rel=1e-6)
