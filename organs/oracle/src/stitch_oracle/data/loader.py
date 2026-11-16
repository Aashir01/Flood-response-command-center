"""Load the committed Oracle demo dataset (``data/demo/oracle/``), offline (ORA-R1.2, R11.1).

Files: ``discharge_daily.parquet`` (modeled GloFAS discharge), ``rain_daily.parquet`` (ERA5 rain
and temperature) and ``stations.json``. The data directory is ``$STITCH_DEMO_DIR`` if set,
otherwise the first ``data/demo`` above this file. Every load is schema-checked: columns and
dtypes, unique keys, contiguous daily dates, no missing values, no negative discharge or rain.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from stitch_oracle.core.features import Frames
from stitch_oracle.core.splits import AS_OF_MIN
from stitch_oracle.core.stations import Catalog, catalog_from_dicts

SUBDIR = "oracle"
DISCHARGE = "discharge_daily.parquet"
WEATHER = "rain_daily.parquet"
STATIONS = "stations.json"
STATION_FIELDS = (
    "station_id",
    "name",
    "river",
    "requested_lat",
    "requested_lon",
    "cell_lat",
    "cell_lon",
    "role",
    "upstream",
    "danger_threshold_m3s",
    "threshold_method",
    "published_warning_cusecs",
    "note",
)


class DatasetError(Exception):
    """The committed dataset is missing or fails validation."""


@dataclass(frozen=True)
class DemoData:
    frames: Frames
    catalog: Catalog
    meta: dict[str, Any]
    start: date
    end: date

    @property
    def as_of_min(self) -> date:
        return AS_OF_MIN

    @property
    def as_of_max(self) -> date:
        return self.end

    @property
    def built_at(self) -> str:
        return str(self.meta.get("built_at", ""))


def demo_dir() -> Path:
    env = os.environ.get("STITCH_DEMO_DIR")
    if env:
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "data" / "demo"
        if candidate.is_dir():
            return candidate
    return Path("data") / "demo"


def _check_daily(df: pd.DataFrame, key: str, name: str) -> tuple[date, date]:
    if df.duplicated(["date", key]).any():
        raise DatasetError(f"{name}: duplicate (date, {key}) rows")
    start, end = min(df["date"]), max(df["date"])
    n_days = (end - start).days + 1
    for k, g in df.groupby(key):
        if len(g) != n_days:
            raise DatasetError(f"{name}: {k} is not a contiguous daily series")
    return start, end


def validate_discharge(df: pd.DataFrame) -> tuple[date, date]:
    cols = ["date", "station_id", "discharge_m3s"]
    if list(df.columns) != cols:
        raise DatasetError(f"{DISCHARGE}: columns {list(df.columns)} != {cols}")
    if df["discharge_m3s"].dtype != np.float32:
        raise DatasetError(f"{DISCHARGE}: discharge_m3s must be float32")
    if not all(isinstance(d, date) for d in df["date"].head(5)):
        raise DatasetError(f"{DISCHARGE}: date must be a date column")
    if df["discharge_m3s"].isna().any():
        raise DatasetError(f"{DISCHARGE}: missing values")
    if (df["discharge_m3s"] < 0).any():
        raise DatasetError(f"{DISCHARGE}: negative discharge")
    return _check_daily(df, "station_id", DISCHARGE)


def validate_weather(df: pd.DataFrame) -> tuple[date, date]:
    cols = ["date", "point_id", "precip_mm", "temp_c"]
    if list(df.columns) != cols:
        raise DatasetError(f"{WEATHER}: columns {list(df.columns)} != {cols}")
    for c in ("precip_mm", "temp_c"):
        if df[c].dtype != np.float32:
            raise DatasetError(f"{WEATHER}: {c} must be float32")
        if df[c].isna().any():
            raise DatasetError(f"{WEATHER}: missing values in {c}")
    if (df["precip_mm"] < 0).any():
        raise DatasetError(f"{WEATHER}: negative precipitation")
    return _check_daily(df, "point_id", WEATHER)


def validate_stations(meta: dict[str, Any]) -> Catalog:
    items = meta.get("stations")
    if not isinstance(items, list) or not items:
        raise DatasetError(f"{STATIONS}: no stations")
    for s in items:
        missing = [f for f in STATION_FIELDS if f not in s]
        if missing:
            raise DatasetError(f"{STATIONS}: {s.get('station_id')} lacks {missing}")
    try:
        return catalog_from_dicts(items)
    except (ValueError, KeyError, TypeError) as exc:
        raise DatasetError(f"{STATIONS}: {exc}") from exc


def load_files(root: Path) -> DemoData:
    base = root / SUBDIR
    for name in (DISCHARGE, WEATHER, STATIONS):
        if not (base / name).is_file():
            raise DatasetError(f"missing {SUBDIR}/{name} under {root}")
    meta = json.loads((base / STATIONS).read_text(encoding="utf-8"))
    catalog = validate_stations(meta)
    dis = pd.read_parquet(base / DISCHARGE)
    dis["station_id"] = dis["station_id"].astype(str)
    wea = pd.read_parquet(base / WEATHER)
    wea["point_id"] = wea["point_id"].astype(str)
    start, end = validate_discharge(dis)
    validate_weather(wea)
    unknown = set(dis["station_id"]) - set(catalog.ids)
    if unknown:
        raise DatasetError(f"{DISCHARGE}: stations not in {STATIONS}: {sorted(unknown)}")
    points = meta.get("points", [])
    rain_points = tuple(sorted(p["point_id"] for p in points if p["kind"] == "rain"))
    temps = [p["point_id"] for p in points if p["kind"] == "temp"]
    if not rain_points or len(temps) != 1:
        raise DatasetError(f"{STATIONS}: need rain points and exactly one temperature point")
    frames = Frames(dis, wea, rain_points, temps[0])
    return DemoData(frames, catalog, meta, start, end)


_cache: dict[Path, DemoData] = {}
_lock = threading.Lock()


def load_demo(root: Path | None = None) -> DemoData:
    """Cached per directory."""
    path = (root or demo_dir()).resolve()
    with _lock:
        if path not in _cache:
            _cache[path] = load_files(path)
        return _cache[path]
