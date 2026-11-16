"""Probabilistic forecast metrics (design section 10). Pure numpy.

``crps_q`` is the quantile-approximated CRPS ``2 * sum_tau w_tau * pinball_tau`` over
``tau = (0.1, 0.5, 0.9)`` with weights ``(0.3, 0.4, 0.3)``. It is a coarse surrogate and only
comparable between forecasts scored the same way.
"""

from __future__ import annotations

import numpy as np

TAUS = (0.1, 0.5, 0.9)
CRPS_WEIGHTS = (0.3, 0.4, 0.3)


def pinball(y: np.ndarray, q: np.ndarray, tau: float) -> np.ndarray:
    """Pinball (quantile) loss per sample."""
    d = np.asarray(y, dtype="float64") - np.asarray(q, dtype="float64")
    out: np.ndarray = np.maximum(tau * d, (tau - 1.0) * d)
    return out


def crps_q(y: np.ndarray, q10: np.ndarray, q50: np.ndarray, q90: np.ndarray) -> np.ndarray:
    qs = (q10, q50, q90)
    total = np.zeros(np.shape(y), dtype="float64")
    for w, tau, q in zip(CRPS_WEIGHTS, TAUS, qs, strict=True):
        total = total + w * pinball(y, q, tau)
    return 2.0 * total


def coverage(y: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> float:
    y = np.asarray(y, dtype="float64")
    if y.size == 0:
        return float("nan")
    return float(np.mean((y >= lo) & (y <= hi)))


def width(lo: np.ndarray, hi: np.ndarray) -> float:
    return float(np.mean(np.asarray(hi, dtype="float64") - np.asarray(lo, dtype="float64")))


def brier(p: np.ndarray, event: np.ndarray) -> float:
    p = np.asarray(p, dtype="float64")
    if p.size == 0:
        return float("nan")
    return float(np.mean((p - np.asarray(event, dtype="float64")) ** 2))


def skill(score: float, reference: float) -> float:
    """``1 - score / reference`` (positive is better than the reference)."""
    if reference == 0:
        return float("nan")
    return 1.0 - score / reference
