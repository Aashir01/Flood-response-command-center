"""ORA-P1, P2, P3, P7 (unit), X7, X8: quantile repair and conformalized intervals."""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from oracle_strategies import quantile_triples, score_arrays

from stitch_oracle.core import conformal
from stitch_oracle.core.conformal import ConformityTable, interval, qhat
from stitch_oracle.core.forecast import back_transform
from stitch_oracle.core.quantiles import repair

coverages = st.floats(conformal.COVERAGE_MIN, conformal.COVERAGE_MAX)


def _calibrated(
    triple: tuple[float, float, float], q_hat: float, q_t: float
) -> tuple[float, float, float]:
    rep, _ = repair(np.array([triple]))
    q10, q50, q90 = rep[0]
    lo, hi = interval(np.array([q10]), np.array([q50]), np.array([q90]), np.array([q_hat]))
    ys = np.sort(np.array([lo[0], q50, hi[0]]))
    v = back_transform(ys, q_t)
    return float(v[0]), float(v[1]), float(v[2])


@given(quantile_triples())
def test_repair_sorts_and_flags(triple: tuple[float, float, float]) -> None:
    rep, flag = repair(np.array([triple]))
    assert rep[0, 0] <= rep[0, 1] <= rep[0, 2]
    assert sorted(rep[0].tolist()) == sorted(triple)
    assert bool(flag[0]) == (list(triple) != sorted(triple))


@given(quantile_triples(), st.floats(-5, 5), st.floats(0, 1e6))
def test_ora_p1_p2_calibrated_interval_ordered_finite_nonnegative(
    triple: tuple[float, float, float], q_hat: float, q_t: float
) -> None:
    lo, mid, hi = _calibrated(triple, q_hat, q_t)
    assert lo <= mid <= hi
    assert all(math.isfinite(v) and v >= 0 for v in (lo, mid, hi))


@given(quantile_triples(), score_arrays(), coverages, coverages, st.floats(0, 1e5))
def test_ora_p3_higher_coverage_never_narrower(
    triple: tuple[float, float, float], scores: np.ndarray, c1: float, c2: float, q_t: float
) -> None:
    lo_c, hi_c = sorted((c1, c2))
    a = _calibrated(triple, qhat(scores, lo_c).value, q_t)
    b = _calibrated(triple, qhat(scores, hi_c).value, q_t)
    assert b[0] <= a[0] and b[2] >= a[2]
    assert a[1] == b[1]


@given(score_arrays(), coverages, coverages)
def test_ora_x7_qhat_non_decreasing_in_coverage(scores: np.ndarray, c1: float, c2: float) -> None:
    lo_c, hi_c = sorted((c1, c2))
    assert qhat(scores, lo_c).value <= qhat(scores, hi_c).value


@given(score_arrays(min_n=1, max_n=30))
def test_ora_x7_k_above_n_uses_max_and_flags(scores: np.ndarray) -> None:
    n = len(scores)
    c = 0.99
    q = qhat(scores, c)
    k = math.ceil((n + 1) * c - 1e-12)
    assert q.k_exceeds_n == (k > n)
    if k > n:
        assert q.value == scores[-1]


def test_qhat_hand_computed() -> None:
    s = np.arange(1, 11, dtype=float)  # n = 10
    assert qhat(s, 0.8).value == 9.0  # k = ceil(11 * 0.8) = 9
    assert qhat(s, 0.5).value == 6.0  # k = ceil(5.5) = 6
    assert qhat(s, 0.95).k_exceeds_n  # k = 11 > 10
    with pytest.raises(ValueError):
        qhat(np.array([]), 0.8)


def test_ora_x8_small_calibration_falls_back_to_pooled_and_widens() -> None:
    rng = np.random.default_rng(0)
    raw = {("big", 1): rng.normal(0, 1, 2000), ("small", 1): rng.normal(0, 1, 50)}
    table = ConformityTable.build(raw, min_cal=500)
    big = table.lookup("big", 1, 0.8)
    small = table.lookup("small", 1, 0.8)
    pooled = qhat(table.pooled[1], 0.8).value
    assert not big.pooled and small.pooled and small.n == 50
    assert small.value == pytest.approx(pooled + abs(pooled) / math.sqrt(50))
    assert small.value >= pooled
    # negative Q_c (coverage below the raw band) still widens rather than narrows
    neg = table.lookup("small", 1, 0.5)
    assert neg.value >= qhat(table.pooled[1], 0.5).value


@given(score_arrays(min_n=1, max_n=200), coverages, coverages)
def test_ora_x8_fallback_keeps_nesting(scores: np.ndarray, c1: float, c2: float) -> None:
    table = ConformityTable.build({("s", 1): scores[:10], ("t", 1): scores}, min_cal=500)
    lo_c, hi_c = sorted((c1, c2))
    assert table.lookup("s", 1, lo_c).value <= table.lookup("s", 1, hi_c).value


def test_unknown_lead_raises() -> None:
    table = ConformityTable.build({("s", 1): np.zeros(10)})
    with pytest.raises(LookupError):
        table.lookup("s", 2, 0.8)


@pytest.mark.parametrize("coverage", [0.5, 0.8, 0.9, 0.95])
def test_ora_p7_unit_coverage_on_exchangeable_synthetic_data(coverage: float) -> None:
    """Seeded noise model, 20k test points, n_cal = 2000, tolerance 0.03."""
    rng = np.random.default_rng(42)

    def draw(n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        x = rng.uniform(-1, 1, n)
        y = 0.5 * x + rng.standard_t(4, n) * (0.2 + 0.1 * np.abs(x))
        # a deliberately miscalibrated base model: too narrow
        return y, 0.5 * x - 0.1, 0.5 * x + 0.1

    y_cal, lo_cal, hi_cal = draw(2000)
    s = np.sort(conformal.scores(y_cal, lo_cal, hi_cal))
    q = qhat(s, coverage).value
    y, lo, hi = draw(20000)
    mid = (lo + hi) / 2
    a, b = interval(lo, mid, hi, np.full_like(lo, q))
    cov = float(np.mean((y >= a) & (y <= b)))
    assert cov >= coverage - 0.03


def test_quantile_levels() -> None:
    assert conformal.quantile_levels(0.9) == (0.05, 0.95)
    assert conformal.quantile_levels(0.8) == (0.1, 0.9)
