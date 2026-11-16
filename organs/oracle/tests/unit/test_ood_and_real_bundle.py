"""ORA-X5 (out-of-range flag), the real committed bundle smoke test and latency (ORA-R6.1)."""

from __future__ import annotations

import math
import time
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from stitch_oracle.core import ood
from stitch_oracle.core.bundle import ModelBundle
from stitch_oracle.core.dataset import design_matrix
from stitch_oracle.core.features import FEATURES, build_features, to_wide
from stitch_oracle.core.forecast import Request, forecast
from stitch_oracle.data.loader import load_demo

MODELS = Path(__file__).resolve().parents[2] / "models"
RANGES = {"a": (0.0, 10.0), "b": (-1.0, 1.0)}


def test_ora_x5_flag_fires_outside_and_not_inside() -> None:
    assert ood.out_of_range(["a", "b"], [5.0, 0.0], RANGES) == []
    assert ood.out_of_range(["a", "b"], [10.4, -1.09], RANGES) == []  # inside the 5% margin
    assert ood.out_of_range(["a", "b"], [10.6, 0.0], RANGES) == ["a"]
    assert ood.out_of_range(["a", "b"], [math.nan, 9.0], RANGES) == ["b"]
    w = ood.warning(["a", "b", "c", "d"])
    assert w is not None and "(+1 more)" in w and "extrapolates" in w
    assert ood.warning([]) is None


@given(st.floats(-1e6, 1e6, allow_nan=False), st.floats(0.0, 0.049))
def test_ora_x5_hypothesis(v: float, inside: float) -> None:
    lo, hi = RANGES["a"]
    flagged = ood.out_of_range(["a"], [v], RANGES) == ["a"]
    assert flagged == (v < lo - 0.5 or v > hi + 0.5)
    assert ood.out_of_range(["a"], [hi + inside * 10.0], RANGES) == []


@pytest.fixture(scope="module")
def bundle() -> ModelBundle:
    return ModelBundle.load(MODELS)


def test_real_bundle_sukkur_2022_08_15(bundle: ModelBundle) -> None:
    d = load_demo()
    r = forecast(Request("indus-sukkur", 14, date(2022, 8, 15)), d.frames, d.catalog, bundle)
    vals = [v for p in r.points for v in (p.lo, p.p50, p.hi)]
    assert all(math.isfinite(v) and v >= 0 for v in vals)
    q_t = r.features.q_t
    assert all(0.3 * q_t < p.p50 < 3.0 * q_t for p in r.points)  # plausible scale
    assert r.n_calibration > 1500 and r.threshold_m3s and r.threshold_m3s > 10_000
    # widening with lead on average (ORA-R5.1)
    w = [p.hi - p.lo for p in r.points]
    assert np.mean(w[7:]) > np.mean(w[:7])


def test_real_bundle_ood_fires_when_a_feature_leaves_its_range(bundle: ModelBundle) -> None:
    d = load_demo()
    st_ = d.catalog.get("indus-guddu")
    assert st_ is not None
    row = build_features(d.frames, st_, date(2022, 8, 15), d.catalog, dict(bundle.station_codes))
    vals = list(row.values)
    assert ood.out_of_range(FEATURES, vals, bundle.feature_ranges) == []
    i = FEATURES.index("rain_7")
    vals[i] = bundle.feature_ranges["rain_7"][1] * 3
    assert ood.out_of_range(FEATURES, vals, bundle.feature_ranges) == ["rain_7"]


def test_design_row_equals_serving_row(bundle: ModelBundle) -> None:
    d = load_demo()
    codes = dict(bundle.station_codes)
    dm = design_matrix(to_wide(d.frames), d.catalog, ["indus-kotri"], codes, [1])
    i = int(np.where(dm.dates == date(2022, 8, 15))[0][0])
    st_ = d.catalog.get("indus-kotri")
    assert st_ is not None
    row = build_features(d.frames, st_, date(2022, 8, 15), d.catalog, codes)
    np.testing.assert_array_equal(dm.x[i], row.values)


def test_latency_p95_under_2s(bundle: ModelBundle) -> None:
    d = load_demo()
    times = []
    for day in range(1, 21):
        t0 = time.perf_counter()
        forecast(Request("indus-kotri", 14, date(2022, 8, day)), d.frames, d.catalog, bundle)
        times.append(time.perf_counter() - t0)
    assert float(np.percentile(times, 95)) < 2.0
