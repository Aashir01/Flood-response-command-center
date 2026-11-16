"""Chronological splits with purge (design section 3.3).

A row ``(as_of = t, lead = h)`` belongs to a split only if both ``t`` and ``t + h`` fall inside
it, so no target of one split is dated inside another. ``assert_disjoint`` runs in training and
in tests. No 2022 row enters training or calibration.

The design table starts in 1985. The Open-Meteo Flood API returns no values before 1997 for these
cells, so train_fit starts in 1997 and train_val is 2009-2011 (see docs/decisions.md).
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np


@dataclass(frozen=True)
class Split:
    name: str
    start: date
    end: date

    def contains(self, d: date) -> bool:
        return self.start <= d <= self.end

    def mask(self, as_of: Iterable[date], lead: int) -> np.ndarray:
        """Rows whose origin and target both fall inside the split (purge)."""
        h = timedelta(days=lead)
        return np.array([self.start <= t and t + h <= self.end for t in as_of], dtype=bool)


TRAIN_FIT = Split("train_fit", date(1997, 1, 1), date(2008, 12, 31))
TRAIN_VAL = Split("train_val", date(2009, 1, 1), date(2011, 12, 31))
REFIT = Split("refit", date(1997, 1, 1), date(2011, 12, 31))
CALIBRATION = Split("calibration", date(2012, 1, 1), date(2016, 12, 31))
TEST = Split("test", date(2017, 1, 1), date(2023, 12, 31))
STRESS = Split("stress_2022", date(2022, 6, 1), date(2022, 10, 31))

#: Splits that must not overlap each other (refit is train_fit + train_val by design; stress
#: lies inside test).
DISJOINT: tuple[Split, ...] = (TRAIN_FIT, TRAIN_VAL, CALIBRATION, TEST)
ALL: tuple[Split, ...] = (TRAIN_FIT, TRAIN_VAL, REFIT, CALIBRATION, TEST, STRESS)

#: First valid forecast origin: the calibration set ends before it, so nothing used by the model
#: or its calibration postdates any allowed ``as_of`` (ORA-R2.4).
AS_OF_MIN = TEST.start


def assert_disjoint(splits: Iterable[Split] = DISJOINT) -> None:
    items = sorted(splits, key=lambda s: s.start)
    for a, b in itertools.pairwise(items):
        if b.start <= a.end:
            raise AssertionError(f"splits overlap: {a.name} and {b.name}")
    if not (REFIT.start == TRAIN_FIT.start and REFIT.end == TRAIN_VAL.end):
        raise AssertionError("refit must equal train_fit + train_val")
    if not (REFIT.end < CALIBRATION.start and CALIBRATION.end < TEST.start):
        raise AssertionError("refit, calibration and test must be ordered and disjoint")
    if not (TEST.contains(STRESS.start) and TEST.contains(STRESS.end)):
        raise AssertionError("stress window must lie inside test")


def assert_purged(as_of: Iterable[date], lead: int, split: Split) -> None:
    """Every target date of the selected rows lies inside the split."""
    h = timedelta(days=lead)
    for t in as_of:
        if not (split.contains(t) and split.contains(t + h)):
            raise AssertionError(f"{split.name}: row {t} + {lead} d leaks outside the split")
