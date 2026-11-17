"""Eval building blocks (task 11): metrics on hand-computed examples, baselines, and the
vectorised paths the eval uses (``calibrate_batch``, ``p_exceed_many``) equal the tool's paths."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from stitch_oracle.core import baselines as bl
from stitch_oracle.core import metrics as m
from stitch_oracle.core.bundle import ModelBundle
from stitch_oracle.core.exceedance import Cdf, p_exceed_many
from stitch_oracle.core.features import build_features
from stitch_oracle.core.forecast import Request, calibrate_batch, forecast
from stitch_oracle.data.loader import load_demo
from stitch_oracle.service import DEFAULT_MODELS


def test_pinball_and_crps_hand_computed() -> None:
    y = np.array([10.0])
    assert m.pinball(y, np.array([8.0]), 0.1)[0] == pytest.approx(0.2)
    assert m.pinball(y, np.array([12.0]), 0.1)[0] == pytest.approx(1.8)
    assert m.pinball(y, np.array([12.0]), 0.9)[0] == pytest.approx(0.2)
    # q = (8, 10, 12): pinball 0.2, 0, 0.2 -> 2 * (0.3*0.2 + 0 + 0.3*0.2) = 0.24
    crps = m.crps_q(y, np.array([8.0]), np.array([10.0]), np.array([12.0]))[0]
    assert crps == pytest.approx(0.24)
    # a point forecast scores 2 * (0.3*0.1 + 0.4*0.5 + 0.3*0.9) * |d| = 1.0 * |d|
    assert m.crps_q(y, *(np.array([7.0]),) * 3)[0] == pytest.approx(3.0)


def test_coverage_width_brier_skill() -> None:
    y = np.array([1.0, 2.0, 3.0, 4.0])
    assert m.coverage(y, np.full(4, 1.5), np.full(4, 3.0)) == 0.5
    assert m.width(np.array([0.0, 1.0]), np.array([2.0, 5.0])) == 3.0
    assert m.brier(np.array([0.0, 1.0]), np.array([False, True])) == 0.0
    assert m.brier(np.array([0.5]), np.array([True])) == 0.25
    assert m.skill(1.0, 4.0) == 0.75 and np.isnan(m.skill(1.0, 0.0))
    assert np.isnan(m.coverage(np.array([]), np.array([]), np.array([])))


def test_persistence_baselines() -> None:
    q_t = np.array([0.0, 99.0])
    assert bl.persistence_point(q_t).tolist() == [[0.0] * 3, [99.0] * 3]
    qy = bl.logratio_quantiles(np.array([-1.0, 0.0, 1.0, np.nan]))
    assert qy[1] == 0.0
    out = bl.persistence_prob(q_t, np.array([np.log(0.5), 0.0, np.log(2.0)]))
    assert out[1].tolist() == pytest.approx([49.0, 99.0, 199.0])
    assert out[0, 0] == 0.0  # (0 + 1) * 0.5 - 1 clips at 0
    with pytest.raises(ValueError):
        bl.logratio_quantiles(np.array([np.nan]))


def test_day_of_year_and_circular_climatology_window() -> None:
    assert bl.doy(date(2020, 2, 29)) == 59 and bl.doy(date(2020, 3, 1)) == 60
    assert bl.doy(date(2021, 3, 1)) == 60 and bl.doy(date(2021, 12, 31)) == 365
    days = [date(2001, 1, 1) + timedelta(days=i) for i in range(365)]
    vals = np.array([100.0 if d.month == 1 else 0.0 for d in days])
    table = bl.climatology_table(days, vals, window=3)
    assert table[15].tolist() == [100.0] * 3  # mid January
    assert table[365, 1] == 0.0 and table[365, 2] == pytest.approx(100.0)  # wraps to 1 Jan
    q = bl.climatology(table, [date(2030, 1, 15), date(2030, 7, 1)])
    assert q.shape == (2, 3) and q[1].tolist() == [0.0] * 3


@given(
    st.lists(
        st.tuples(st.floats(0, 1e5), st.floats(0, 1e5), st.floats(0, 1e5), st.floats(0, 2e5)),
        min_size=1,
        max_size=30,
    )
)
def test_p_exceed_many_equals_scalar_path(rows: list[tuple[float, float, float, float]]) -> None:
    q = np.sort(np.array([r[:3] for r in rows]), axis=1)
    thr = np.array([r[3] for r in rows])
    vec = p_exceed_many(q[:, 0], q[:, 1], q[:, 2], thr)
    for i in range(len(rows)):
        ref = Cdf.from_quantiles(*q[i]).p_exceed(float(thr[i]))
        assert vec[i] == pytest.approx(ref, abs=1e-9)


def test_p_exceed_many_at_knots() -> None:
    q = np.array([[100.0, 200.0, 400.0]] * 3)
    p = p_exceed_many(q[:, 0], q[:, 1], q[:, 2], np.array([200.0, 0.0, 1e9]))
    assert p.tolist() == pytest.approx([0.5, 1.0, 0.0])


def test_calibrate_batch_equals_the_tool_pipeline() -> None:
    """The eval's vectorised path gives the tool's numbers (up to the tool's rounding)."""
    data = load_demo()
    bundle = ModelBundle.load(DEFAULT_MODELS)
    for sid, as_of, cov in (
        ("indus-sukkur", date(2022, 8, 15), 0.8),
        ("indus-kotri", date(2019, 3, 1), 0.9),
        ("chenab-trimmu", date(2022, 7, 10), 0.5),
    ):
        res = forecast(Request(sid, 14, as_of, cov), data.frames, data.catalog, bundle)
        st_ = data.catalog.get(sid)
        assert st_ is not None
        row = build_features(data.frames, st_, as_of, data.catalog, dict(bundle.station_codes))
        raw = bundle.predict(row.values[None, :])[0]
        for j, p in enumerate(res.points):
            qh = bundle.conformity.lookup(sid, p.lead, cov).value
            got = calibrate_batch(raw[j][None, :], np.array([row.q_t]), np.array([qh]))[0]
            assert got.tolist() == pytest.approx([p.lo, p.p50, p.hi], abs=1e-3)
