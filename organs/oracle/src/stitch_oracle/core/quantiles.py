"""Quantile monotonicity repair (design section 4.3, ORA-R2.3, ORA-P1).

Sorting the three raw quantiles of a lead is the minimal L1 repair for three values. The flag
per lead says whether a crossing was repaired, so the tool can report it.
"""

from __future__ import annotations

import numpy as np


def repair(q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """``q`` has shape ``(..., 3)`` (q10, q50, q90). Returns the sorted array and a boolean flag
    of shape ``q.shape[:-1]`` that is true where the input was not already ordered."""
    arr = np.asarray(q, dtype="float64")
    if arr.shape[-1] != 3:
        raise ValueError("last axis must hold (q10, q50, q90)")
    out = np.sort(arr, axis=-1)
    flags = np.any(out != arr, axis=-1)
    return out, flags
