"""ORA-P6: exceedance in [0, 1], non-increasing in the threshold; hand-computed values."""

from __future__ import annotations

import itertools
import math

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from stitch_oracle.core.exceedance import Cdf

pos = st.floats(0.0, 1e6, allow_nan=False, allow_infinity=False)


@st.composite
def knots(draw: st.DrawFn) -> tuple[float, float, float]:
    vals = sorted(draw(st.lists(pos, min_size=3, max_size=3)))
    if draw(st.booleans()):  # zero-width cases
        i = draw(st.integers(0, 1))
        vals[i + 1] = vals[i]
    return vals[0], vals[1], vals[2]


@given(knots(), st.lists(st.floats(0.0, 2e6, allow_nan=False), min_size=2, max_size=20))
def test_ora_p6_bounded_and_non_increasing(k: tuple[float, float, float], ts: list[float]) -> None:
    cdf = Cdf.from_quantiles(*k)
    ps = [cdf.p_exceed(t) for t in sorted(ts)]
    assert all(0.0 <= p <= 1.0 for p in ps)
    assert all(a >= b for a, b in itertools.pairwise(ps))


@given(knots())
def test_p_exceed_at_median_is_one_half(k: tuple[float, float, float]) -> None:
    assume(k[0] < k[1] < k[2])
    assert Cdf.from_quantiles(*k).p_exceed(k[1]) == pytest.approx(0.5, abs=1e-9)


def test_hand_computed_knots() -> None:
    cdf = Cdf.from_quantiles(math.e**1 - 1, math.e**2 - 1, math.e**3 - 1)  # x = 1, 2, 3
    assert cdf.p_exceed(math.e**1 - 1) == pytest.approx(0.9)
    assert cdf.p_exceed(math.e**3 - 1) == pytest.approx(0.1)
    assert cdf.p_exceed(math.e**2.5 - 1) == pytest.approx(0.3)
    # tails: slope 0.4 per unit x, pseudo-knots at x = 1 - 0.225 and 3 + 0.225
    assert cdf.x[0] == pytest.approx(1 - 0.09 / 0.4)
    assert cdf.x[4] == pytest.approx(3 + 0.09 / 0.4)
    assert cdf.p_exceed(0.0) == 1.0
    assert cdf.p_exceed(1e9) == 0.0
    assert cdf.in_tail(1e9) and not cdf.in_tail(math.e**2 - 1)


def test_lower_tail_clipped_at_zero_discharge() -> None:
    cdf = Cdf.from_quantiles(1.0, 100.0, 200.0)
    assert cdf.x[0] == 0.0
    assert cdf.p_exceed(0.0) <= 1.0


def test_zero_width_is_a_step() -> None:
    cdf = Cdf.from_quantiles(50.0, 50.0, 50.0)
    assert cdf.p_exceed(49.0) == 1.0
    assert cdf.p_exceed(50.0) == pytest.approx(0.01)
    assert cdf.p_exceed(51.0) == 0.0


def test_unordered_knots_rejected() -> None:
    with pytest.raises(ValueError):
        Cdf.from_quantiles(3.0, 2.0, 1.0)
