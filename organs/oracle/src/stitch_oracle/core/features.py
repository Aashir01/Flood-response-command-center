"""Feature construction (design section 3.2). The only place that reads history.

No-leakage rule (ORA-R2.4, ORA-P5): ``build_features`` slices every frame to ``date <= as_of``
*before* computing anything, and every operation in ``feature_table`` is causal (shifts and
trailing windows), so the row for day ``t`` depends only on rows dated ``<= t``.

Target per lead ``h``: ``y_h = ln(Q[t+h] + 1) - ln(Q[t] + 1)`` (log ratio to the current modeled
discharge). ``Q`` is modeled GloFAS discharge, never a gauge record.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from stitch_oracle.core.stations import Catalog, Station

LAGS = (1, 3, 7, 14, 30)
UP_LAGS = (1, 3, 7)
RAIN_WINDOWS = (1, 3, 7, 14, 30)
UPSTREAM_SLOTS = 2
#: Longest trailing window used by any feature, in days.
MAX_WINDOW = 45

FEATURES: tuple[str, ...] = (
    "lnq",
    *(f"dlnq_{k}" for k in LAGS),
    "max7_rel",
    "min7_rel",
    *(
        name
        for slot in range(1, UPSTREAM_SLOTS + 1)
        for name in (f"up{slot}_rel", *(f"up{slot}_d{k}" for k in UP_LAGS))
    ),
    *(f"rain_{k}" for k in RAIN_WINDOWS),
    "rain_max7",
    "temp_7",
    "temp_d14",
    "doy_sin",
    "doy_cos",
    "monsoon",
    "station",
)
STATION_FEATURE = "station"

#: Feature family, used for ``Driver.feature_group`` and the narrative.
GROUPS: dict[str, str] = {
    "level_trend": "level and trend of modeled discharge",
    "upstream": "modeled upstream discharge",
    "rainfall": "basin rainfall (ERA5)",
    "temperature": "upper-basin temperature (ERA5)",
    "season": "season",
    "station": "station identity",
}


def feature_group(name: str) -> str:
    if name.startswith("up"):
        return "upstream"
    if name.startswith("rain"):
        return "rainfall"
    if name.startswith("temp"):
        return "temperature"
    if name in ("doy_sin", "doy_cos", "monsoon"):
        return "season"
    if name == STATION_FEATURE:
        return "station"
    return "level_trend"


@dataclass(frozen=True)
class Frames:
    """Long-format history. ``discharge``: ``date, station_id, discharge_m3s``. ``weather``:
    ``date, point_id, precip_mm, temp_c``. ``rain_points`` are averaged into the basin mean;
    ``temp_point`` supplies temperature."""

    discharge: pd.DataFrame
    weather: pd.DataFrame
    rain_points: tuple[str, ...]
    temp_point: str

    def until(self, as_of: date) -> Frames:
        """Every frame sliced to ``date <= as_of`` (the first step of every read)."""
        return Frames(
            self.discharge[self.discharge["date"] <= as_of],
            self.weather[self.weather["date"] <= as_of],
            self.rain_points,
            self.temp_point,
        )


@dataclass(frozen=True)
class Wide:
    q: pd.DataFrame  # date index (daily, contiguous) x station_id, m3/s
    precip: pd.DataFrame  # date index x rain point, mm/day
    temp: pd.Series  # date index, deg C


def to_wide(frames: Frames) -> Wide:
    """Pivot to a contiguous daily index. Row and column order of the input do not matter
    (ORA-X6); missing days become NaN (the gap rules in ``gaps.py`` act on them)."""
    d = frames.discharge
    if d.duplicated(["date", "station_id"]).any():
        raise ValueError("duplicate (date, station_id) rows in discharge")
    w = frames.weather
    if w.duplicated(["date", "point_id"]).any():
        raise ValueError("duplicate (date, point_id) rows in weather")
    q = d.pivot(index="date", columns="station_id", values="discharge_m3s").astype("float64")
    q = q.sort_index().reindex(sorted(q.columns), axis=1)
    if q.empty:
        raise ValueError("no discharge history")
    idx = pd.date_range(q.index.min(), q.index.max(), freq="D").date
    q = q.reindex(idx)
    p = w.pivot(index="date", columns="point_id", values="precip_mm").astype("float64")
    t = w.pivot(index="date", columns="point_id", values="temp_c").astype("float64")
    missing = [pt for pt in frames.rain_points if pt not in p.columns]
    precip = p.reindex(columns=list(frames.rain_points)).reindex(idx)
    if missing:
        precip.loc[:, missing] = np.nan
    temp = (
        t[frames.temp_point].reindex(idx)
        if frames.temp_point in t.columns
        else pd.Series(np.nan, index=idx)
    )
    return Wide(q, precip, temp.astype("float64"))


def feature_table(
    wide: Wide, station: Station, catalog: Catalog, station_codes: dict[str, int]
) -> pd.DataFrame:
    """Features for every day of ``wide`` for one station. Causal: row ``t`` uses rows ``<= t``."""
    q = wide.q
    if station.station_id not in q.columns:
        raise KeyError(f"no discharge history for {station.station_id}")
    lnq = np.log1p(q[station.station_id])
    out: dict[str, pd.Series] = {"lnq": lnq}
    for k in LAGS:
        out[f"dlnq_{k}"] = lnq - lnq.shift(k)
    out["max7_rel"] = lnq.rolling(7, min_periods=7).max() - lnq
    out["min7_rel"] = lnq.rolling(7, min_periods=7).min() - lnq
    nan = pd.Series(np.nan, index=q.index)
    for slot in range(1, UPSTREAM_SLOTS + 1):
        up = station.upstream[slot - 1] if len(station.upstream) >= slot else None
        if up is not None and catalog.get(up) is not None and up in q.columns:
            lu = np.log1p(q[up])
            out[f"up{slot}_rel"] = lu - lnq
            for k in UP_LAGS:
                out[f"up{slot}_d{k}"] = lu - lu.shift(k)
        else:
            out[f"up{slot}_rel"] = nan
            for k in UP_LAGS:
                out[f"up{slot}_d{k}"] = nan
    pm = wide.precip.mean(axis=1, skipna=False)
    for k in RAIN_WINDOWS:
        out[f"rain_{k}"] = pm.rolling(k, min_periods=k).sum()
    out["rain_max7"] = wide.precip.rolling(7, min_periods=7).sum().max(axis=1, skipna=False)
    t7 = wide.temp.rolling(7, min_periods=7).mean()
    out["temp_7"] = t7
    out["temp_d14"] = t7 - t7.shift(14)
    doy = np.array([d.timetuple().tm_yday for d in q.index], dtype="float64")
    ang = 2.0 * np.pi * (doy - 1.0) / 365.25
    out["doy_sin"] = pd.Series(np.sin(ang), index=q.index)
    out["doy_cos"] = pd.Series(np.cos(ang), index=q.index)
    out["monsoon"] = pd.Series(
        np.array([1.0 if 6 <= d.month <= 9 else 0.0 for d in q.index]), index=q.index
    )
    out["station"] = pd.Series(float(station_codes[station.station_id]), index=q.index)
    table = pd.DataFrame(out, index=q.index)
    return table.loc[:, list(FEATURES)]


def targets(wide: Wide, station_id: str, leads: range) -> pd.DataFrame:
    """``y_h`` for every day and lead (training only; reads the future by definition)."""
    lnq = np.log1p(wide.q[station_id])
    return pd.DataFrame({h: lnq.shift(-h) - lnq for h in leads}, index=wide.q.index)


@dataclass(frozen=True)
class FeatureRow:
    as_of: date
    q_t: float  # modeled discharge on as_of (the back-transform anchor), m3/s
    values: np.ndarray  # shape (len(FEATURES),), float64, NaN allowed

    def as_dict(self) -> dict[str, float | None]:
        return {
            f: (None if np.isnan(v) else float(v))
            for f, v in zip(FEATURES, self.values, strict=True)
        }


def build_features(
    frames: Frames,
    station: Station,
    as_of: date,
    catalog: Catalog,
    station_codes: dict[str, int],
) -> FeatureRow:
    """Feature row of ``station`` at ``as_of``. Slices to ``<= as_of`` first (ORA-P5)."""
    return row_from_wide(to_wide(frames.until(as_of)), station, as_of, catalog, station_codes)


def row_from_wide(
    wide: Wide,
    station: Station,
    as_of: date,
    catalog: Catalog,
    station_codes: dict[str, int],
) -> FeatureRow:
    """Last row of the feature table; ``wide`` must already end at ``as_of``."""
    if len(wide.q.index) == 0 or wide.q.index[-1] != as_of:
        raise LookupError(f"no modeled discharge for {as_of.isoformat()}")
    table = feature_table(wide, station, catalog, station_codes)
    row = table.iloc[-1].to_numpy(dtype="float64")
    q_t = float(wide.q[station.station_id].iloc[-1])
    if not np.isfinite(q_t):
        raise LookupError(f"modeled discharge for {station.station_id} missing on {as_of}")
    return FeatureRow(as_of=as_of, q_t=q_t, values=row)
