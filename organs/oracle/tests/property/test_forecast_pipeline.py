"""End-to-end properties of the core forecast with the stub model: ORA-P1, P2, P4, X1, X2, X9."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from oracle_strategies import make_catalog, make_frames, stub_model

from stitch_oracle.core.features import Frames
from stitch_oracle.core.forecast import ForecastError, Request, forecast

START = date(2016, 6, 1)  # history reaches the 2017-01-01 valid window
N_DAYS = 400
FRAMES = make_frames(11, 3, N_DAYS, start=START)
CAT = make_catalog(3)
MODEL = stub_model(CAT)
LAST = START + timedelta(days=N_DAYS - 1)
NO_THRESHOLD = make_catalog(3, threshold=None)


@st.composite
def requests(draw: st.DrawFn) -> Request:
    span = (LAST - date(2017, 1, 1)).days
    return Request(
        station_id=draw(st.sampled_from(CAT.forecast_ids)),
        horizon_days=draw(st.integers(1, 14)),
        as_of=date(2017, 1, 1) + timedelta(days=draw(st.integers(0, span))),
        coverage=draw(st.floats(0.5, 0.99)),
    )


@settings(deadline=None)
@given(requests())
def test_ora_p1_p2_x1_x2_forecast_shape_and_order(req: Request) -> None:
    r = forecast(req, FRAMES, CAT, MODEL)
    assert [p.lead for p in r.points] == list(range(1, req.horizon_days + 1))
    assert all(p.date == r.as_of + timedelta(days=p.lead) for p in r.points)
    for p in r.points:
        assert 0 <= p.lo <= p.p50 <= p.hi
        assert p.lo80 <= p.p50 <= p.hi80
    assert len(r.exceedance) == len(r.points)
    assert all(0 <= pe <= 1 for _, pe in r.exceedance)
    none = forecast(req, FRAMES, NO_THRESHOLD, MODEL)
    assert none.exceedance == () and none.threshold_m3s is None


@settings(deadline=None)
@given(requests(), st.integers(0, 2**31 - 1))
def test_ora_p4_deterministic_and_order_free(req: Request, seed: int) -> None:
    a = forecast(req, FRAMES, CAT, MODEL)
    b = forecast(req, FRAMES, CAT, MODEL)
    shuffled = Frames(
        FRAMES.discharge.sample(frac=1.0, random_state=seed % 2**32),
        FRAMES.weather.sample(frac=1.0, random_state=(seed + 7) % 2**32),
        FRAMES.rain_points,
        FRAMES.temp_point,
    )
    c = forecast(req, shuffled, CAT, MODEL)
    assert a.points == b.points == c.points
    assert a.exceedance == b.exceedance == c.exceedance
    assert a.warnings == b.warnings == c.warnings


@settings(deadline=None)
@given(requests())
def test_ora_p5_end_to_end_future_rows_ignored(req: Request) -> None:
    assert req.as_of is not None
    full = forecast(req, FRAMES, CAT, MODEL)
    cut = forecast(req, FRAMES.until(req.as_of), CAT, MODEL)
    assert full.points == cut.points and full.exceedance == cut.exceedance


def test_coverage_nesting_end_to_end() -> None:
    lo = forecast(Request("st-2", 14, LAST, 0.6), FRAMES, CAT, MODEL)
    hi = forecast(Request("st-2", 14, LAST, 0.95), FRAMES, CAT, MODEL)
    for a, b in zip(lo.points, hi.points, strict=True):
        assert b.lo <= a.lo and b.hi >= a.hi and a.p50 == b.p50


def test_repair_is_reported() -> None:
    reps = [forecast(Request(s, 14, LAST), FRAMES, CAT, MODEL) for s in CAT.forecast_ids]
    flagged = [r for r in reps if r.any_repair]
    assert flagged, "the stub crosses quantiles for some inputs"
    assert all(any("quantile crossing repaired" in w for w in r.warnings) for r in flagged)


@pytest.mark.parametrize(
    ("req", "code"),
    [
        (Request("st-0", 0, LAST), "INVALID_INPUT"),
        (Request("st-0", 15, LAST), "INVALID_INPUT"),
        (Request("st-0", 3, LAST, coverage=0.3), "INVALID_INPUT"),
        (Request("st-0", 3, date(2016, 12, 31)), "INVALID_INPUT"),
        (Request("st-0", 3, LAST + timedelta(days=1)), "INVALID_INPUT"),
        (Request("nowhere", 3, LAST), "NOT_FOUND"),
    ],
)
def test_ora_x9_invalid_requests(req: Request, code: str) -> None:
    with pytest.raises(ForecastError) as exc:
        forecast(req, FRAMES, CAT, MODEL)
    assert exc.value.code == code


def test_unknown_station_lists_nearby_ids() -> None:
    with pytest.raises(ForecastError) as exc:
        forecast(Request("st-9", 3, LAST), FRAMES, CAT, MODEL)
    assert "nearby stations: " in exc.value.message
    assert any(s in exc.value.message for s in CAT.forecast_ids)


def test_default_as_of_is_last_date_with_warning() -> None:
    r = forecast(Request("st-1", 2), FRAMES, CAT, MODEL)
    assert r.as_of == LAST
    assert any("as_of not given" in w for w in r.warnings)


def test_small_calibration_warns() -> None:
    model = stub_model(CAT, small="st-1")
    r = forecast(Request("st-1", 3, LAST), FRAMES, CAT, model)
    assert any("calibration set below" in w for w in r.warnings)


def test_long_gap_is_upstream_unavailable_and_short_gap_is_filled() -> None:
    d = FRAMES.discharge
    for k, expect in ((2, None), (3, "UPSTREAM_UNAVAILABLE")):
        drop = {LAST - timedelta(days=5 + i) for i in range(k)}
        gappy = Frames(
            d[~((d["station_id"] == "st-2") & d["date"].isin(drop))],
            FRAMES.weather,
            FRAMES.rain_points,
            FRAMES.temp_point,
        )
        if expect is None:
            r = forecast(Request("st-2", 3, LAST), gappy, CAT, MODEL)
            assert any("forward-filled" in w for w in r.warnings)
        else:
            with pytest.raises(ForecastError) as exc:
                forecast(Request("st-2", 3, LAST), gappy, CAT, MODEL)
            assert exc.value.code == expect and exc.value.retryable
