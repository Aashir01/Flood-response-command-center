"""Threshold baselines for the evaluation (design 3.4): per-chip Otsu on VH and a fixed global
VH threshold fitted on the train split. Pure NumPy."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

VH_RANGE = (-35.0, 5.0)


def otsu_threshold(values: npt.ArrayLike, bins: int = 256) -> float:
    """Otsu threshold of finite ``values`` within ``VH_RANGE`` (maximises between-class var)."""
    v = np.asarray(values, dtype=np.float64).ravel()
    v = v[np.isfinite(v)]
    if v.size == 0:
        return float("nan")
    hist, edges = np.histogram(np.clip(v, *VH_RANGE), bins=bins, range=VH_RANGE)
    centers = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    s0 = np.cumsum(hist * centers)
    m0 = np.divide(s0, w0, out=np.zeros_like(s0), where=w0 > 0)
    m1 = np.divide(s0[-1] - s0, w1, out=np.zeros_like(s0), where=w1 > 0)
    between = w0 * w1 * (m0 - m1) ** 2
    k = int(np.argmax(between))
    return float(edges[k + 1])


def otsu_mask(vh: npt.ArrayLike, valid: npt.ArrayLike | None = None) -> npt.NDArray[np.bool_]:
    a = np.asarray(vh, dtype=np.float64)
    sel = a if valid is None else a[np.asarray(valid, dtype=bool)]
    t = otsu_threshold(sel)
    if not np.isfinite(t):
        return np.zeros(a.shape, dtype=bool)
    return a < t


def fit_global_threshold(
    vh_chips: Sequence[npt.ArrayLike], labels: Sequence[npt.ArrayLike]
) -> float:
    """VH threshold (0.1 dB grid, -30..-10 dB) maximising pooled water IoU on the given chips."""
    grid = np.round(np.arange(-30.0, -10.0 + 1e-9, 0.1), 1)
    tp = np.zeros(grid.size)
    fp = np.zeros(grid.size)
    fn = np.zeros(grid.size)
    for vh, lab in zip(vh_chips, labels, strict=True):
        v = np.asarray(vh, dtype=np.float64)
        lb = np.asarray(lab)
        keep = lb != -1
        x = v[keep]
        t = lb[keep] == 1
        xw = np.sort(x[t])
        xn = np.sort(x[~t])
        below_w = np.searchsorted(xw, grid, side="left")
        below_n = np.searchsorted(xn, grid, side="left")
        tp += below_w
        fn += xw.size - below_w
        fp += below_n
    iou = tp / np.maximum(tp + fp + fn, 1)
    return float(grid[int(np.argmax(iou))])
