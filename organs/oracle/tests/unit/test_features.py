"""Features on hand-computed tiny series, and train/serve parity (ORA-R2.4)."""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from oracle_strategies import RAIN_POINTS, TEMP_POINT, make_catalog, make_frames

from stitch_oracle.core.features import (
    FEATURES,
    Frames,
    build_features,
    feature_group,
    feature_table,
    targets,
    to_wide,
)

START = date(2020, 1, 1)


def _frames(q: list[float], up: list[float] | None = None, rain: float = 2.0) -> Frames:
    n = len(q)
    days = [START + timedelta(days=i) for i in range(n)]
    rows = [pd.DataFrame({"date": days, "station_id": "st-1", "discharge_m3s": q})]
    if up is not None:
        rows.append(pd.DataFrame({"date": days, "station_id": "st-0", "discharge_m3s": up}))
    dis = pd.concat(rows, ignore_index=True).astype({"discharge_m3s": "float32"})
    w = []
    for pt in (*RAIN_POINTS, TEMP_POINT):
        w.append(
            pd.DataFrame(
                {
                    "date": days,
                    "point_id": pt,
                    "precip_mm": [rain if pt == "rain-a" else 0.0] * n,
                    "temp_c": [float(i) for i in range(n)],
                }
            ).astype({"precip_mm": "float32", "temp_c": "float32"})
        )
    return Frames(dis, pd.concat(w, ignore_index=True), RAIN_POINTS, TEMP_POINT)


def _row(frames: Frames, as_of: date, n_st: int = 2) -> dict[str, float | None]:
    cat = make_catalog(n_st)
    codes = {s: i for i, s in enumerate(sorted(cat.ids))}
    return build_features(frames, cat.get("st-1"), as_of, cat, codes).as_dict()  # type: ignore[arg-type]


def test_level_trend_and_window_features() -> None:
    q = [float(i * 10) for i in range(40)]  # 0, 10, ..., 390
    up = [float(i * 20) for i in range(40)]
    r = _row(_frames(q, up), START + timedelta(days=39))
    ln = np.log1p
    assert r["lnq"] == pytest.approx(ln(390))
    for k in (1, 3, 7, 14, 30):
        assert r[f"dlnq_{k}"] == pytest.approx(ln(390) - ln(390 - 10 * k))
    assert r["max7_rel"] == pytest.approx(0.0)
    assert r["min7_rel"] == pytest.approx(ln(330) - ln(390))
    assert r["up1_rel"] == pytest.approx(ln(780) - ln(390))
    assert r["up1_d3"] == pytest.approx(ln(780) - ln(720))
    assert r["up2_rel"] is None  # st-1 has one upstream: slot 2 is NaN


def test_rain_temperature_and_season() -> None:
    q = [100.0] * 40
    r = _row(_frames(q, [50.0] * 40, rain=2.0), START + timedelta(days=39))
    # basin mean of (2, 0) = 1 mm/day
    assert r["rain_1"] == pytest.approx(1.0)
    assert r["rain_7"] == pytest.approx(7.0)
    assert r["rain_30"] == pytest.approx(30.0)
    assert r["rain_max7"] == pytest.approx(14.0)
    assert r["temp_7"] == pytest.approx(np.mean(range(33, 40)))
    assert r["temp_d14"] == pytest.approx(14.0)
    as_of = START + timedelta(days=39)
    doy = as_of.timetuple().tm_yday
    assert r["doy_sin"] == pytest.approx(math.sin(2 * math.pi * (doy - 1) / 365.25))
    assert r["monsoon"] == 0.0


def test_short_history_gives_nan_not_error() -> None:
    r = _row(_frames([10.0] * 10, [5.0] * 10), START + timedelta(days=9))
    assert r["dlnq_14"] is None and r["rain_30"] is None and r["dlnq_7"] is not None


def test_target_is_log_ratio() -> None:
    q = [float(i + 1) for i in range(20)]
    wide = to_wide(_frames(q, q))
    y = targets(wide, "st-1", range(1, 3))
    assert y.iloc[0][1] == pytest.approx(np.log1p(2) - np.log1p(1))
    assert np.isnan(y.iloc[-1][1])


def test_every_feature_has_a_group() -> None:
    assert len(FEATURES) == len(set(FEATURES))
    assert {feature_group(f) for f in FEATURES} == {
        "level_trend",
        "upstream",
        "rainfall",
        "temperature",
        "season",
        "station",
    }


def test_serving_row_equals_training_table_row() -> None:
    frames = make_frames(7, 3, 300)
    cat = make_catalog(3)
    codes = {s: i for i, s in enumerate(sorted(cat.ids))}
    st = cat.get("st-2")
    assert st is not None
    table = feature_table(to_wide(frames), st, cat, codes)
    for offset in (40, 150, 299):
        as_of = date(2016, 1, 1) + timedelta(days=offset)
        row = build_features(frames, st, as_of, cat, codes).values
        np.testing.assert_array_equal(row, table.loc[as_of].to_numpy())


def test_missing_as_of_row_is_lookup_error() -> None:
    frames = make_frames(1, 1, 80)
    cat = make_catalog(1)
    with pytest.raises(LookupError):
        build_features(frames, cat.stations[0], date(2030, 1, 1), cat, {"st-0": 0})
