"""Optional live mode (design section 6, ORA-R1.3, R11.2). Used only when ``mode = live`` is
requested; demo mode never imports the network path.

Fetches the last ``PAST_DAYS`` days of modeled GloFAS discharge (Open-Meteo Flood API) for the
station and its upstream cells, and daily rain and temperature for the ERA5 points from the
Open-Meteo Forecast API (``past_days``; the ERA5 archive lags real time by several days). Each
successful fetch is cached as Parquet. On failure the last cache is used with a warning; with no
usable cache ``LiveUnavailable`` is raised and the service falls back to demo data with a
``MODE_FALLBACK`` warning.

Caveat, stated in a warning: live rain comes from the forecast model's recent analysis, not from
ERA5, so its distribution can differ from the training features.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from stitch_oracle.core.features import Frames
from stitch_oracle.data.loader import DemoData

FLOOD_URL = "https://flood-api.open-meteo.com/v1/flood"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
PAST_DAYS = 92
CACHE_ENV = "STITCH_ORACLE_LIVE_CACHE"
TIMEOUT_S = 10.0

Fetcher = Callable[[str, dict[str, str]], Any]


class LiveUnavailable(Exception):
    """Live data could not be fetched and no usable cache exists."""


def http_get_json(url: str, params: dict[str, str]) -> Any:
    query = urllib.parse.urlencode(params, safe=",")
    req = urllib.request.Request(
        f"{url}?{query}", headers={"User-Agent": "stitch-oracle/0.2 (non-commercial demo)"}
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _items(resp: Any) -> list[dict[str, Any]]:
    return resp if isinstance(resp, list) else [resp]


class OpenMeteoLive:
    def __init__(
        self,
        cache_dir: Path,
        fetch: Fetcher = http_get_json,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.cache_dir = cache_dir
        self.fetch = fetch
        self.now = now

    @staticmethod
    def from_env() -> OpenMeteoLive:
        return OpenMeteoLive(Path(os.environ.get(CACHE_ENV) or "data/cache/oracle"))

    # ------------------------------------------------------------------ fetch
    def _fetch(
        self, station_ids: Sequence[str], demo: DemoData
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        cells = [demo.catalog.get(s) for s in station_ids]
        if any(c is None for c in cells):
            raise LiveUnavailable("unknown station for live fetch")
        lat = ",".join(f"{c.cell_lat:.4f}" for c in cells if c is not None)
        lon = ",".join(f"{c.cell_lon:.4f}" for c in cells if c is not None)
        flood = self.fetch(
            FLOOD_URL,
            {
                "latitude": lat,
                "longitude": lon,
                "daily": "river_discharge",
                "past_days": str(PAST_DAYS),
                "forecast_days": "1",
                "cell_selection": "nearest",
                "timezone": "GMT",
            },
        )
        today = self.now().date()
        rows = []
        for sid, item in zip(station_ids, _items(flood), strict=True):
            for d, v in zip(item["daily"]["time"], item["daily"]["river_discharge"], strict=True):
                day = date.fromisoformat(d)
                if day < today and v is not None:  # only days before today
                    rows.append((day, sid, float(v)))
        dis = pd.DataFrame(rows, columns=["date", "station_id", "discharge_m3s"])
        points = demo.meta.get("points", [])
        wx = self.fetch(
            FORECAST_URL,
            {
                "latitude": ",".join(f"{p['cell_lat']:.3f}" for p in points),
                "longitude": ",".join(f"{p['cell_lon']:.3f}" for p in points),
                "daily": "precipitation_sum,temperature_2m_mean",
                "past_days": str(PAST_DAYS),
                "forecast_days": "1",
                "timezone": "GMT",
            },
        )
        wrows = []
        for p, item in zip(points, _items(wx), strict=True):
            daily = item["daily"]
            for d, pr, t in zip(
                daily["time"],
                daily["precipitation_sum"],
                daily["temperature_2m_mean"],
                strict=True,
            ):
                day = date.fromisoformat(d)
                if day < today and pr is not None and t is not None:
                    wrows.append((day, p["point_id"], max(float(pr), 0.0), float(t)))
        wea = pd.DataFrame(wrows, columns=["date", "point_id", "precip_mm", "temp_c"])
        if dis.empty or wea.empty:
            raise LiveUnavailable("live response had no data")
        dis["discharge_m3s"] = dis["discharge_m3s"].astype(np.float32)
        wea[["precip_mm", "temp_c"]] = wea[["precip_mm", "temp_c"]].astype(np.float32)
        return dis, wea

    # ------------------------------------------------------------------ cache
    def _write_cache(self, dis: pd.DataFrame, wea: pd.DataFrame) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        dis.to_parquet(self.cache_dir / "live_discharge.parquet", index=False)
        wea.to_parquet(self.cache_dir / "live_weather.parquet", index=False)
        meta = {"fetched_at": self.now().strftime("%Y-%m-%dT%H:%M:%SZ")}
        (self.cache_dir / "live_meta.json").write_text(json.dumps(meta), encoding="utf-8")

    def _read_cache(self, station_ids: Sequence[str]) -> tuple[pd.DataFrame, pd.DataFrame, str]:
        try:
            dis = pd.read_parquet(self.cache_dir / "live_discharge.parquet")
            wea = pd.read_parquet(self.cache_dir / "live_weather.parquet")
            meta = json.loads((self.cache_dir / "live_meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise LiveUnavailable("no live cache") from exc
        if not set(station_ids) <= set(dis["station_id"]):
            raise LiveUnavailable("live cache does not cover the station")
        return dis, wea, str(meta.get("fetched_at", "unknown time"))

    def frames(self, station_ids: list[str], demo: DemoData) -> tuple[Frames, list[str]]:
        notes = [
            "live mode: modeled GloFAS discharge from the Open-Meteo Flood API (recent days are "
            "GloFAS forecast-based values); rain and temperature from the Open-Meteo Forecast "
            "API analysis, not ERA5, so inputs can differ from the training distribution"
        ]
        try:
            dis, wea = self._fetch(station_ids, demo)
            self._write_cache(dis, wea)
        except Exception as exc:
            dis, wea, when = self._read_cache(station_ids)
            notes.append(
                f"live fetch failed ({type(exc).__name__}); using cached live data from {when}"
            )
        frames = Frames(dis, wea, demo.frames.rain_points, demo.frames.temp_point)
        return frames, notes
