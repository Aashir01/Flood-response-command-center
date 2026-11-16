"""Shared Hypothesis strategies and the stub model (design section 11).

``history_frames()`` draws a seed and sizes, then builds the series with numpy: shrinking acts on
the seed and sizes, and generation stays fast. ``StubModel`` is a deterministic function of the
features with no LightGBM, and crosses its quantiles for some inputs so the repair path runs.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd
from hypothesis import strategies as st

from stitch_oracle.core.conformal import ConformityTable
from stitch_oracle.core.features import FEATURES, Frames
from stitch_oracle.core.stations import Catalog, Station

LEADS = tuple(range(1, 15))
RAIN_POINTS = ("rain-a", "rain-b")
TEMP_POINT = "temp-a"


def make_catalog(n: int, threshold: float | None = 500.0) -> Catalog:
    stations = []
    for i in range(n):
        up = (f"st-{i - 1}",) if i > 0 else ()
        stations.append(
            Station(
                station_id=f"st-{i}",
                name=f"Place {i}",
                river="Test",
                requested_lat=25.0 + i,
                requested_lon=68.0 + i,
                cell_lat=25.0 + i + 0.025,
                cell_lon=68.0 + i + 0.025,
                role="forecast",
                upstream=up,
                danger_threshold_m3s=threshold,
                threshold_method="modeled_5yr_return_level" if threshold is not None else None,
            )
        )
    return Catalog(tuple(stations))


def make_frames(seed: int, n_stations: int, n_days: int, start: date = date(2016, 1, 1)) -> Frames:
    rng = np.random.default_rng(seed)
    days = [start + timedelta(days=i) for i in range(n_days)]
    rows = []
    for i in range(n_stations):
        level = rng.uniform(1.0, 9.0)
        walk = level + np.cumsum(rng.normal(0, 0.05, n_days))
        q = np.exp(walk).astype("float32")
        rows.append(
            pd.DataFrame(
                {"date": days, "station_id": f"st-{i}", "discharge_m3s": q.astype("float32")}
            )
        )
    discharge = pd.concat(rows, ignore_index=True)
    w = []
    for pt in (*RAIN_POINTS, TEMP_POINT):
        rain = np.where(rng.random(n_days) < 0.3, rng.gamma(1.5, 6.0, n_days), 0.0)
        temp = 15 + 10 * np.sin(np.arange(n_days) / 58.0) + rng.normal(0, 1, n_days)
        w.append(
            pd.DataFrame(
                {
                    "date": days,
                    "point_id": pt,
                    "precip_mm": rain.astype("float32"),
                    "temp_c": temp.astype("float32"),
                }
            )
        )
    weather = pd.concat(w, ignore_index=True)
    return Frames(discharge, weather, RAIN_POINTS, TEMP_POINT)


@st.composite
def history_frames(draw: st.DrawFn) -> tuple[Frames, Catalog]:
    seed = draw(st.integers(0, 2**31 - 1))
    n_st = draw(st.integers(1, 3))
    n_days = draw(st.integers(60, 400))
    return make_frames(seed, n_st, n_days), make_catalog(n_st)


def quantile_triples() -> st.SearchStrategy[tuple[float, float, float]]:
    f = st.floats(-60.0, 60.0, allow_nan=False, allow_infinity=False)
    return st.tuples(f, f, f)


def score_arrays(min_n: int = 1, max_n: int = 3000) -> st.SearchStrategy[np.ndarray]:
    @st.composite
    def _scores(draw: st.DrawFn) -> np.ndarray:
        n = draw(st.integers(min_n, max_n))
        seed = draw(st.integers(0, 2**31 - 1))
        signed = draw(st.booleans())
        rng = np.random.default_rng(seed)
        x = rng.normal(0, 0.3, n) if signed else np.abs(rng.normal(0, 0.3, n))
        return np.sort(x)

    return _scores()


@dataclass
class StubModel:
    """Deterministic stand-in for ``ModelBundle``."""

    station_codes: Mapping[str, int]
    conformity: ConformityTable
    leads: tuple[int, ...] = LEADS
    features: tuple[str, ...] = FEATURES
    feature_ranges: Mapping[str, tuple[float, float]] = field(default_factory=dict)
    name: str = "stub"
    version: str = "0"
    sha256: str = "0" * 64

    def _q(self, x: np.ndarray) -> np.ndarray:
        x = np.nan_to_num(np.atleast_2d(x), nan=0.0)
        trend = np.tanh(x[:, 1])  # dlnq_1
        out = np.empty((x.shape[0], len(self.leads), 3))
        for j, h in enumerate(self.leads):
            mid = 0.02 * h * trend
            half = 0.03 * np.sqrt(h)
            wobble = 0.05 * np.sin(x[:, 0] * h)  # crosses q50 over q90 for some inputs
            out[:, j, 0] = mid - half
            out[:, j, 1] = mid + wobble
            out[:, j, 2] = mid + half
        return out

    def predict(self, x: np.ndarray) -> np.ndarray:
        return self._q(x)

    def contrib(self, x: np.ndarray, lead: int) -> np.ndarray:
        q = self._q(x)[:, self.leads.index(lead), 1]
        x = np.atleast_2d(x)
        phi = np.zeros((x.shape[0], len(self.features) + 1))
        phi[:, 1] = q * 0.7
        phi[:, 0] = q * 0.3
        return phi


def stub_model(
    catalog: Catalog, n_cal: int = 600, seed: int = 0, small: str | None = None
) -> StubModel:
    rng = np.random.default_rng(seed)
    raw = {}
    for s in catalog.stations:
        for h in LEADS:
            n = 50 if s.station_id == small else n_cal
            raw[(s.station_id, h)] = rng.normal(0.0, 0.02 * np.sqrt(h), n)
    codes = {sid: i for i, sid in enumerate(sorted(catalog.ids))}
    return StubModel(codes, ConformityTable.build(raw))


@st.composite
def valid_requests(draw: st.DrawFn, catalog: Catalog, first: date, last: date) -> dict[str, object]:
    sid = draw(st.sampled_from(catalog.forecast_ids))
    span = (last - first).days
    as_of = first + timedelta(days=draw(st.integers(0, span)))
    return {
        "station_id": sid,
        "horizon_days": draw(st.integers(1, 14)),
        "as_of": as_of,
        "coverage": draw(st.floats(0.5, 0.99)),
    }
