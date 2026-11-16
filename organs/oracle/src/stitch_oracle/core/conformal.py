"""Conformalized quantile regression (design section 4.4, ORA-R3, ORA-P3).

Scores live in target space (log ratio), ``E_i = max(q10_i - y_i, y_i - q90_i)``, stored sorted
per (station, lead). For nominal coverage ``c``: ``k = ceil((n + 1) c)`` and
``Q_c = score_sorted[min(k, n) - 1]``; ``k > n`` uses the maximum score and warns.

Nesting (ORA-P3): ``Q_c`` indexes a sorted array at a rank that is non-decreasing in ``c``, so
it is non-decreasing in ``c``; the interval ``[q10' - Q_c, q90' + Q_c]`` (with the median kept
inside) therefore only grows with ``c``.

Small calibration sets (ORA-R3.4): below ``MIN_CAL`` points for a (station, lead) the pooled
scores of all stations for that lead are used and ``Q_c`` is widened to
``Q_c + |Q_c| / sqrt(n_station)``. That map is non-decreasing in ``Q_c``, so nesting holds, and it
always widens (multiplying a negative ``Q_c`` by ``1 + 1/sqrt(n)`` would narrow it instead).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np

MIN_CAL = 500
COVERAGE_MIN = 0.5
COVERAGE_MAX = 0.99
DEFAULT_COVERAGE = 0.8


def scores(y: np.ndarray, q10: np.ndarray, q90: np.ndarray) -> np.ndarray:
    """CQR conformity scores."""
    y = np.asarray(y, dtype="float64")
    out: np.ndarray = np.maximum(
        np.asarray(q10, dtype="float64") - y, y - np.asarray(q90, dtype="float64")
    )
    return out


def rank(n: int, coverage: float) -> int:
    """1-based rank ``k = ceil((n + 1) c)`` (with a guard against float noise)."""
    return math.ceil((n + 1) * coverage - 1e-12)


@dataclass(frozen=True)
class QHat:
    value: float
    n: int  # calibration points behind the value (the station's own n when it fell back)
    k_exceeds_n: bool = False
    pooled: bool = False


def qhat(sorted_scores: np.ndarray, coverage: float) -> QHat:
    """Empirical conformal quantile of a sorted score array. Raises on an empty array."""
    n = int(sorted_scores.shape[0])
    if n == 0:
        raise ValueError("no calibration scores")
    k = rank(n, coverage)
    idx = min(max(k, 1), n) - 1
    return QHat(float(sorted_scores[idx]), n, k_exceeds_n=k > n)


@dataclass(frozen=True)
class ConformityTable:
    """Sorted scores per ``(station_id, lead)``; pooled per lead for the small-n fallback."""

    by_station: Mapping[tuple[str, int], np.ndarray]
    pooled: Mapping[int, np.ndarray] = field(default_factory=dict)
    min_cal: int = MIN_CAL

    @staticmethod
    def build(raw: Mapping[tuple[str, int], np.ndarray], min_cal: int = MIN_CAL) -> ConformityTable:
        by = {key: np.sort(np.asarray(v, dtype="float64")) for key, v in raw.items()}
        leads = sorted({lead for _, lead in by})
        pooled = {
            lead: np.sort(np.concatenate([v for (_, h), v in by.items() if h == lead]))
            for lead in leads
        }
        return ConformityTable(by, pooled, min_cal)

    def n(self, station_id: str, lead: int) -> int:
        arr = self.by_station.get((station_id, lead))
        return 0 if arr is None else int(arr.shape[0])

    def lookup(self, station_id: str, lead: int, coverage: float) -> QHat:
        own = self.by_station.get((station_id, lead))
        n_own = 0 if own is None else int(own.shape[0])
        if n_own >= self.min_cal:
            assert own is not None
            return qhat(own, coverage)
        pooled = self.pooled.get(lead)
        if pooled is None or pooled.shape[0] == 0:
            raise LookupError(f"no calibration scores for lead {lead}")
        base = qhat(pooled, coverage)
        widened = base.value + abs(base.value) / math.sqrt(max(n_own, 1))
        return QHat(widened, n_own, k_exceeds_n=base.k_exceeds_n, pooled=True)


def interval(
    q10: np.ndarray, q50: np.ndarray, q90: np.ndarray, q_hat: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Calibrated interval in target space for repaired quantiles (``q10 <= q50 <= q90``). The
    median stays inside when ``Q_c`` is negative (coverage below the raw 0.8 band)."""
    lo = np.minimum(np.asarray(q10) - q_hat, q50)
    hi = np.maximum(np.asarray(q90) + q_hat, q50)
    return lo, hi


def quantile_levels(coverage: float) -> tuple[float, float]:
    """Quantile levels of the interval bounds (contract ``interval_lower_q/upper_q``)."""
    return round((1.0 - coverage) / 2.0, 10), round((1.0 + coverage) / 2.0, 10)
