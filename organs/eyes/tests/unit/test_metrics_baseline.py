"""Eval metrics with the ignore index and the threshold baselines (design 3.4, task 5)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from stitch_eyes.core.baseline import fit_global_threshold, otsu_mask, otsu_threshold
from stitch_eyes.core.metrics import Counts, bootstrap_ci, counts, mean_chip_iou, pooled


def test_counts_on_a_hand_computed_mask_with_ignored_pixels() -> None:
    label = np.array([[1, 1, 0, 0], [1, -1, -1, 0]])
    pred = np.array([[1, 0, 1, 0], [1, 1, 0, 1]])
    c = counts(pred, label)
    assert (c.tp, c.fp, c.fn, c.tn) == (2, 2, 1, 1)
    assert c.iou == pytest.approx(2 / 5)
    assert c.f1 == pytest.approx(4 / 7)
    assert c.precision == pytest.approx(0.5) and c.recall == pytest.approx(2 / 3)
    extra = np.zeros_like(label, dtype=bool)
    extra[0, 2] = True
    assert counts(pred, label, extra).fp == 1


def test_undefined_metrics_are_nan_and_pooling_adds() -> None:
    z = Counts(0, 0, 0, 10)
    assert math.isnan(z.iou) and math.isnan(z.precision)
    a, b = Counts(1, 2, 3, 4), Counts(5, 0, 1, 0)
    assert pooled([a, b]) == Counts(6, 2, 4, 4)
    assert mean_chip_iou([a, b, z]) == pytest.approx((1 / 6 + 5 / 6) / 2)
    with pytest.raises(ValueError):
        counts(np.zeros((2, 2)), np.zeros((3, 3)))


def test_bootstrap_ci_brackets_the_pooled_value_and_is_seeded() -> None:
    rng = np.random.default_rng(0)
    chips = [Counts(*(int(v) for v in rng.integers(0, 100, 4))) for _ in range(30)]
    lo, hi = bootstrap_ci(chips, "iou", n=300, seed=0)
    assert lo <= pooled(chips).iou <= hi
    assert (lo, hi) == bootstrap_ci(chips, "iou", n=300, seed=0)


def test_otsu_splits_a_bimodal_vh_histogram() -> None:
    rng = np.random.default_rng(1)
    water = rng.normal(-24.0, 1.0, 4000)
    land = rng.normal(-14.0, 1.5, 6000)
    t = otsu_threshold(np.concatenate([water, land]))
    assert -21.0 < t < -17.0
    vh = np.concatenate([water, land]).reshape(100, 100)
    m = otsu_mask(vh)
    assert m[:40].mean() > 0.99 and m[60:].mean() < 0.01
    assert not otsu_mask(np.full((3, 3), np.nan)).any()


def test_global_threshold_fit_on_synthetic_chips() -> None:
    rng = np.random.default_rng(2)
    vh, lab = [], []
    for _ in range(4):
        y = (rng.random((50, 50)) < 0.3).astype(np.int16)
        v = np.where(y == 1, rng.normal(-25, 1, y.shape), rng.normal(-13, 1, y.shape))
        y[0, :5] = -1
        vh.append(v)
        lab.append(y)
    t = fit_global_threshold(vh, lab)
    assert -22.0 <= t <= -16.0
