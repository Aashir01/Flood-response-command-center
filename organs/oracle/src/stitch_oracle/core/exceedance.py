"""Exceedance probability from quantile knots (design section 4.5, ORA-R4.2, ORA-P6).

The CDF ``F`` of ``x = ln(Q + 1)`` is piecewise linear through the knots
``(x10, 0.1), (x50, 0.5), (x90, 0.9)`` (the 0.8-calibrated interval ends and the median), with
the tails extended linearly, using the slope of the adjacent segment, to pseudo-knots at
``F = 0.01`` and ``F = 0.99`` (the lower one clipped at ``x = 0``, i.e. ``Q = 0``). ``F`` is 0
below the first knot and 1 above the last. Equal ``x`` values become vertical steps and ``F``
is right-continuous there. ``p_exceed(T) = 1 - F(ln(T + 1))``.

``F`` is non-decreasing, so ``p_exceed`` is in [0, 1] and non-increasing in ``T`` (ORA-P6).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

F_KNOTS = (0.01, 0.10, 0.50, 0.90, 0.99)


@dataclass(frozen=True)
class Cdf:
    x: tuple[float, float, float, float, float]  # non-decreasing, ln(Q + 1)

    @staticmethod
    def from_quantiles(q10: float, q50: float, q90: float) -> Cdf:
        """Knots from discharge quantiles in m3/s (``0 <= q10 <= q50 <= q90``)."""
        x10, x50, x90 = (math.log1p(max(v, 0.0)) for v in (q10, q50, q90))
        if not (x10 <= x50 <= x90):
            raise ValueError("quantile knots must be ordered")
        lo_slope = (x50 - x10) / (0.50 - 0.10)
        hi_slope = (x90 - x50) / (0.90 - 0.50)
        x01 = max(0.0, x10 - lo_slope * (0.10 - 0.01))
        x99 = x90 + hi_slope * (0.99 - 0.90)
        return Cdf((min(x01, x10), x10, x50, x90, x99))

    def cdf(self, x: float) -> float:
        xs = self.x
        if x < xs[0]:
            return 0.0
        if x > xs[-1]:
            return 1.0
        # last knot with xs[i] <= x (right-continuous at steps)
        i = int(np.searchsorted(np.asarray(xs), x, side="right")) - 1
        if i >= len(xs) - 1:
            return F_KNOTS[-1]
        x0, x1 = xs[i], xs[i + 1]
        f0, f1 = F_KNOTS[i], F_KNOTS[i + 1]
        if x1 == x0:  # cannot happen with side="right", kept for safety
            return f1
        return f0 + (f1 - f0) * (x - x0) / (x1 - x0)

    def p_exceed(self, threshold_m3s: float) -> float:
        p = 1.0 - self.cdf(math.log1p(max(threshold_m3s, 0.0)))
        return min(1.0, max(0.0, p))

    @staticmethod
    def knots_many(q10: np.ndarray, q50: np.ndarray, q90: np.ndarray) -> np.ndarray:
        """Vectorised ``from_quantiles``: knots of many CDFs, shape ``(n, 5)``."""
        x10, x50, x90 = (
            np.log1p(np.maximum(np.asarray(v, "float64"), 0.0)) for v in (q10, q50, q90)
        )
        if np.any(x10 > x50) or np.any(x50 > x90):
            raise ValueError("quantile knots must be ordered")
        lo_slope = (x50 - x10) / (0.50 - 0.10)
        hi_slope = (x90 - x50) / (0.90 - 0.50)
        x01 = np.maximum(0.0, x10 - lo_slope * (0.10 - 0.01))
        x99 = x90 + hi_slope * (0.99 - 0.90)
        return np.stack([np.minimum(x01, x10), x10, x50, x90, x99], axis=1)

    def in_tail(self, threshold_m3s: float) -> bool:
        """True when the threshold falls outside the calibrated band, where ``F`` is
        extrapolated."""
        x = math.log1p(max(threshold_m3s, 0.0))
        return x < self.x[1] or x > self.x[3]


def p_exceed_many(
    q10: np.ndarray, q50: np.ndarray, q90: np.ndarray, threshold_m3s: np.ndarray
) -> np.ndarray:
    """Vectorised ``Cdf.from_quantiles(...).p_exceed(T)`` row by row (used by the eval; equal to
    the scalar path, tested)."""
    xs = Cdf.knots_many(q10, q50, q90)
    x = np.log1p(np.maximum(np.asarray(threshold_m3s, dtype="float64"), 0.0))
    x = np.broadcast_to(x, xs[:, 0].shape)
    fk = np.asarray(F_KNOTS)
    i = np.sum(xs <= x[:, None], axis=1) - 1
    j = np.clip(i, 0, len(F_KNOTS) - 2)
    rows = np.arange(xs.shape[0])
    x0, x1 = xs[rows, j], xs[rows, j + 1]
    span = x1 - x0
    frac = np.divide(x - x0, span, out=np.ones_like(x0), where=span > 0)
    f = fk[j] + (fk[j + 1] - fk[j]) * frac
    f = np.where(i >= len(F_KNOTS) - 1, F_KNOTS[-1], f)
    f = np.where(x < xs[:, 0], 0.0, np.where(x > xs[:, -1], 1.0, f))
    out: np.ndarray = np.clip(1.0 - f, 0.0, 1.0)
    return out
