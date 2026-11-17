"""Segmentation metrics for the water class with an ignore index (design 3.4). Pure NumPy."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

IGNORE = -1


@dataclass(frozen=True)
class Counts:
    tp: int
    fp: int
    fn: int
    tn: int

    def __add__(self, other: Counts) -> Counts:
        return Counts(
            self.tp + other.tp, self.fp + other.fp, self.fn + other.fn, self.tn + other.tn
        )

    @property
    def iou(self) -> float:
        d = self.tp + self.fp + self.fn
        return self.tp / d if d else float("nan")

    @property
    def f1(self) -> float:
        d = 2 * self.tp + self.fp + self.fn
        return 2 * self.tp / d if d else float("nan")

    @property
    def precision(self) -> float:
        d = self.tp + self.fp
        return self.tp / d if d else float("nan")

    @property
    def recall(self) -> float:
        d = self.tp + self.fn
        return self.tp / d if d else float("nan")

    def as_dict(self) -> dict[str, float]:
        return {
            "iou": self.iou,
            "f1": self.f1,
            "precision": self.precision,
            "recall": self.recall,
        }


def counts(
    pred: npt.ArrayLike, label: npt.ArrayLike, extra_ignore: npt.ArrayLike | None = None
) -> Counts:
    """Confusion counts of a binary ``pred`` against ``label`` (1 water, 0 not, -1 ignored).

    ``extra_ignore`` (bool) removes more pixels, e.g. the scene's nodata pixels.
    """
    p = np.asarray(pred).astype(bool)
    lab = np.asarray(label)
    if p.shape != lab.shape:
        raise ValueError("pred and label shapes differ")
    keep = lab != IGNORE
    if extra_ignore is not None:
        keep &= ~np.asarray(extra_ignore, dtype=bool)
    t = lab == 1
    tp = int(np.count_nonzero(p & t & keep))
    fp = int(np.count_nonzero(p & ~t & keep))
    fn = int(np.count_nonzero(~p & t & keep))
    tn = int(np.count_nonzero(~p & ~t & keep))
    return Counts(tp, fp, fn, tn)


def pooled(per_chip: Sequence[Counts]) -> Counts:
    total = Counts(0, 0, 0, 0)
    for c in per_chip:
        total = total + c
    return total


def mean_chip_iou(per_chip: Sequence[Counts]) -> float:
    """Mean of per-chip IoU over chips where IoU is defined (some water in pred or label)."""
    vals = [c.iou for c in per_chip if (c.tp + c.fp + c.fn) > 0]
    return float(np.mean(vals)) if vals else float("nan")


def bootstrap_ci(
    per_chip: Sequence[Counts],
    metric: str = "iou",
    n: int = 1000,
    seed: int = 0,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Percentile CI of the pooled ``metric`` by resampling chips with replacement."""
    if not per_chip:
        return (float("nan"), float("nan"))
    arr = np.array([[c.tp, c.fp, c.fn, c.tn] for c in per_chip], dtype=np.int64)
    rng = np.random.default_rng(seed)
    vals: list[float] = []
    for _ in range(n):
        idx = rng.integers(0, len(arr), len(arr))
        s = arr[idx].sum(axis=0)
        vals.append(getattr(Counts(*(int(v) for v in s)), metric))
    finite = np.array([v for v in vals if np.isfinite(v)])
    if finite.size == 0:
        return (float("nan"), float("nan"))
    lo, hi = np.quantile(finite, [alpha / 2, 1 - alpha / 2])
    return (float(lo), float(hi))
