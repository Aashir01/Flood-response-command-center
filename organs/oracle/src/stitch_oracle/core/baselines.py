"""Reference forecasts for the eval (design section 10). Pure numpy.

* Persistence (point): every quantile equals the modeled discharge at ``as_of``.
* Persistence (probabilistic): empirical quantiles of the log ratio ``y_h`` per lead, from the
  training split, applied to the anchor: ``Q = (Q_t + 1) exp(q_tau) - 1``.
* Climatology: quantiles of the modeled discharge on the same day of year (+-15 days, circular)
  over the training years, per station, looked up at the target date.

All discharge is modeled GloFAS discharge (via Open-Meteo).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import numpy as np

TAUS = (0.1, 0.5, 0.9)
CLIM_WINDOW = 15


def persistence_point(q_t: np.ndarray) -> np.ndarray:
    """Shape ``(n, 3)``: the anchor repeated for every quantile."""
    q = np.asarray(q_t, dtype="float64")
    return np.repeat(q[:, None], 3, axis=1)


def logratio_quantiles(y: np.ndarray, taus: Sequence[float] = TAUS) -> np.ndarray:
    """Empirical quantiles of finite log ratios, shape ``(len(taus),)``."""
    v = np.asarray(y, dtype="float64")
    v = v[np.isfinite(v)]
    if v.size == 0:
        raise ValueError("no finite training targets")
    out: np.ndarray = np.asarray(np.quantile(v, list(taus)), dtype="float64")
    return out


def persistence_prob(q_t: np.ndarray, qy: np.ndarray) -> np.ndarray:
    """Shape ``(n, 3)``: ``(Q_t + 1) exp(q_tau) - 1``, clipped at 0."""
    a = np.asarray(q_t, dtype="float64")[:, None] + 1.0
    out: np.ndarray = np.maximum(a * np.exp(np.asarray(qy, dtype="float64")[None, :]) - 1.0, 0.0)
    return out


def doy(d: date) -> int:
    """Day of year 1..365; 29 February maps to 28 February (day 59)."""
    n = d.timetuple().tm_yday
    leap = d.year % 4 == 0 and (d.year % 100 != 0 or d.year % 400 == 0)
    return n - 1 if leap and n > 59 else n


def climatology_table(
    dates: Sequence[date], values: np.ndarray, window: int = CLIM_WINDOW
) -> np.ndarray:
    """Quantiles per day of year, shape ``(366, 3)`` (row 0 unused), from training values."""
    v = np.asarray(values, dtype="float64")
    days = np.array([doy(d) for d in dates], dtype="int64")
    ok = np.isfinite(v)
    v, days = v[ok], days[ok]
    if v.size == 0:
        raise ValueError("no training values for climatology")
    table = np.full((366, 3), np.nan)
    for k in range(1, 366):
        dist = np.abs(days - k)
        dist = np.minimum(dist, 365 - dist)
        sel = v[dist <= window]
        if sel.size:
            table[k] = np.quantile(sel, list(TAUS))
    return table


def climatology(table: np.ndarray, target_dates: Sequence[date]) -> np.ndarray:
    """Shape ``(n, 3)``: the table row of each target date."""
    idx = np.array([doy(d) for d in target_dates], dtype="int64")
    out: np.ndarray = table[idx]
    return out
