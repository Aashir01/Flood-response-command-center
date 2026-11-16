"""ORA-P5 (no leakage) and ORA-X6 (order invariance) for the feature builder, and the split
table (design section 3.3) with its purge guard."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from oracle_strategies import history_frames

from stitch_oracle.core import splits
from stitch_oracle.core.features import Frames, build_features
from stitch_oracle.core.stations import Catalog


def _codes(cat: Catalog) -> dict[str, int]:
    return {s: i for i, s in enumerate(sorted(cat.ids))}


@given(history_frames(), st.floats(0.2, 0.9), st.integers(0, 2**31 - 1), st.booleans())
def test_ora_p5_future_rows_do_not_change_features(
    hf: tuple[Frames, Catalog], frac: float, seed: int, delete: bool
) -> None:
    frames, cat = hf
    days = sorted(set(frames.discharge["date"]))
    as_of = days[int(frac * (len(days) - 1))]
    station = cat.stations[-1]
    before = build_features(frames, station, as_of, cat, _codes(cat)).values

    rng = np.random.default_rng(seed)
    d = frames.discharge.copy()
    w = frames.weather.copy()
    fut_d, fut_w = d["date"] > as_of, w["date"] > as_of
    if delete:
        d, w = d[~fut_d], w[~fut_w]
    else:
        vals = rng.uniform(0, 1e6, int(fut_d.sum())).astype("float32")
        vals[: len(vals) // 3] = np.nan
        d.loc[fut_d, "discharge_m3s"] = vals
        w.loc[fut_w, "precip_mm"] = rng.uniform(0, 500, int(fut_w.sum())).astype("float32")
    after = build_features(
        Frames(d, w, frames.rain_points, frames.temp_point), station, as_of, cat, _codes(cat)
    ).values
    np.testing.assert_array_equal(before, after)


@given(history_frames(), st.integers(0, 2**31 - 1))
def test_ora_x6_row_and_station_order_do_not_matter(hf: tuple[Frames, Catalog], seed: int) -> None:
    frames, cat = hf
    as_of = max(frames.discharge["date"])
    station = cat.stations[-1]
    a = build_features(frames, station, as_of, cat, _codes(cat)).values
    shuffled = Frames(
        frames.discharge.sample(frac=1.0, random_state=seed % 2**32),
        frames.weather.sample(frac=1.0, random_state=(seed + 1) % 2**32),
        frames.rain_points,
        frames.temp_point,
    )
    reversed_cat = Catalog(tuple(reversed(cat.stations)))
    b = build_features(shuffled, station, as_of, reversed_cat, _codes(cat)).values
    np.testing.assert_array_equal(a, b)


def test_split_table_matches_design() -> None:
    table = {s.name: (s.start, s.end) for s in splits.ALL}
    assert table == {
        "train_fit": (date(1997, 1, 1), date(2008, 12, 31)),
        "train_val": (date(2009, 1, 1), date(2011, 12, 31)),
        "refit": (date(1997, 1, 1), date(2011, 12, 31)),
        "calibration": (date(2012, 1, 1), date(2016, 12, 31)),
        "test": (date(2017, 1, 1), date(2023, 12, 31)),
        "stress_2022": (date(2022, 6, 1), date(2022, 10, 31)),
    }
    splits.assert_disjoint()
    assert date(2017, 1, 1) == splits.AS_OF_MIN


def test_no_2022_row_in_training_or_calibration() -> None:
    for s in (splits.REFIT, splits.CALIBRATION):
        assert s.end < date(2022, 1, 1)


@pytest.mark.parametrize("lead", [1, 7, 14])
def test_purge_drops_rows_whose_target_leaves_the_split(lead: int) -> None:
    s = splits.CALIBRATION
    days = [s.end - timedelta(days=i) for i in range(30)]
    mask = s.mask(days, lead)
    kept = [d for d, m in zip(days, mask, strict=True) if m]
    assert all(d + timedelta(days=lead) <= s.end for d in kept)
    assert sum(not m for m in mask) == lead
    splits.assert_purged(kept, lead, s)
    with pytest.raises(AssertionError):
        splits.assert_purged([s.end], lead, s)


def test_overlapping_splits_are_rejected() -> None:
    bad = splits.Split("bad", date(2016, 6, 1), date(2018, 1, 1))
    with pytest.raises(AssertionError):
        splits.assert_disjoint((*splits.DISJOINT, bad))
