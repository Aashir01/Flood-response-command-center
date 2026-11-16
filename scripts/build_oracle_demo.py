"""Build the Oracle demo dataset from Open-Meteo (dev time only, needs the network once).

    uv run python scripts/build_oracle_demo.py            # fetch (cached in data/raw/oracle/)
    uv run python scripts/build_oracle_demo.py --offline  # rebuild from the raw cache only

Writes ``data/demo/oracle/{discharge_daily,rain_daily}.parquet``, ``stations.json`` and
``MANIFEST.md`` (oracle-mcp design section 3). The discharge series is **modeled** GloFAS v4
river discharge from the Open-Meteo Flood API. It is not a gauge record. Rain and temperature
are ERA5 reanalysis from the Open-Meteo Historical Weather API.

Steps:
1. Cell probing per station: a 5x5 grid of offsets at 0.05 degrees around the requested point,
   ``cell_selection=nearest``, one request per station over a short window. The cell with the
   highest mean discharge is kept; requested and returned coordinates are printed and recorded.
2. Discharge: one request per station, 1984-01-01..2023-12-31, ``timezone=GMT``.
3. ERA5 daily precipitation and mean temperature: one request per point.
4. Validation: no gaps, no negatives, a continuity check over 2022-06-01..2023-12-31 and a
   report of the series around the end of the GloFAS v4 reanalysis (July 2022).
5. Danger thresholds: modeled 5-year return level from annual maxima of 1997-2016 only.

Rate limits (Open-Meteo free tier, non-commercial): fewer than 30 requests in total, with a pause
between requests and exponential backoff on HTTP 429. No API key.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data" / "raw" / "oracle"
OUT = REPO / "data" / "demo" / "oracle"

FLOOD_URL = "https://flood-api.open-meteo.com/v1/flood"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
# The Flood API documents data from 1984, but for these cells it returns null for every day
# before 1997-01-01 (checked 2026-11-17), so the dataset starts in 1997.
START = date(1997, 1, 1)
FETCH_START = date(1984, 1, 1)
END = date(2023, 12, 31)
PROBE_START, PROBE_END = date(2015, 6, 1), date(2015, 9, 30)
THRESHOLD_YEARS = (1997, 2016)
CONTINUITY = (date(2022, 6, 1), date(2023, 12, 31))
JOIN_DATE = date(2022, 7, 31)  # last day of the GloFAS v4 reanalysis per the Open-Meteo docs
PAUSE_S = 15.0
USER_AGENT = "stitch-oracle-build/0.1 (hackathon demo; non-commercial)"


@dataclass(frozen=True)
class StationSpec:
    station_id: str
    name: str
    river: str
    lat: float
    lon: float
    role: str
    upstream: tuple[str, ...]
    note: str


STATIONS: tuple[StationSpec, ...] = (
    StationSpec(
        "indus-kalabagh",
        "Indus near Kalabagh",
        "Indus",
        32.96,
        71.55,
        "feature",
        (),
        "Feature only: upstream input for Taunsa.",
    ),
    StationSpec(
        "kabul-nowshera",
        "Kabul near Nowshera",
        "Kabul",
        34.00,
        71.98,
        "feature",
        (),
        "Feature only: Kabul river inflow above the Indus confluence.",
    ),
    StationSpec(
        "chenab-trimmu",
        "Chenab near Trimmu",
        "Chenab",
        31.15,
        72.15,
        "forecast",
        (),
        "Tributary; joins the Indus above Guddu via the Panjnad.",
    ),
    StationSpec(
        "indus-taunsa",
        "Indus near Taunsa",
        "Indus",
        30.51,
        70.85,
        "forecast",
        ("indus-kalabagh", "kabul-nowshera"),
        "",
    ),
    StationSpec(
        "indus-guddu",
        "Indus near Guddu",
        "Indus",
        28.42,
        69.72,
        "forecast",
        ("indus-taunsa", "chenab-trimmu"),
        "",
    ),
    StationSpec(
        "indus-sukkur",
        "Indus near Sukkur",
        "Indus",
        27.69,
        68.85,
        "forecast",
        ("indus-guddu", "indus-taunsa"),
        "",
    ),
    StationSpec(
        "indus-kotri",
        "Indus near Kotri",
        "Indus",
        25.37,
        68.31,
        "forecast",
        ("indus-sukkur", "indus-guddu"),
        "Kotri flow is shaped by barrage operation and canal withdrawals that GloFAS "
        "does not model.",
    ),
)


@dataclass(frozen=True)
class PointSpec:
    point_id: str
    name: str
    lat: float
    lon: float
    kind: str  # rain | temp


POINTS: tuple[PointSpec, ...] = (
    PointSpec("rain-swat", "Swat / lower Kabul basin", 34.80, 72.30, "rain"),
    PointSpec("rain-jhelum", "Upper Jhelum (Muzaffarabad)", 34.30, 73.70, "rain"),
    PointSpec("rain-chenab", "Chenab foothills (Jammu)", 32.90, 74.90, "rain"),
    PointSpec("rain-sulaiman", "Sulaiman range hill torrents", 30.30, 69.80, "rain"),
    PointSpec("temp-gilgit", "Upper Indus (Gilgit), snowmelt proxy", 35.90, 74.30, "temp"),
)


def log(msg: str) -> None:
    print(msg, flush=True)


# ------------------------------------------------------------------ network (cached)
def _get(url: str, params: dict[str, str], cache: Path, offline: bool) -> Any:
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    if offline:
        raise SystemExit(f"--offline: raw cache missing: {cache.relative_to(REPO)}")
    query = urllib.parse.urlencode(params, safe=",")
    full = f"{url}?{query}"
    delay = 30.0
    for attempt in range(6):
        req = urllib.request.Request(full, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = resp.read().decode("utf-8")
            break
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 502, 503) and attempt < 5:
                log(f"  HTTP {exc.code}, backing off {delay:.0f} s")
                time.sleep(delay)
                delay *= 2
                continue
            raise
        except urllib.error.URLError:
            if attempt < 5:
                log(f"  network error, retry in {delay:.0f} s")
                time.sleep(delay)
                delay *= 2
                continue
            raise
    data = json.loads(body)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps({"url": full, "fetched_at": _now(), "response": data}), encoding="utf-8"
    )
    time.sleep(PAUSE_S)
    return {"url": full, "fetched_at": _now(), "response": data}


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_list(response: Any) -> list[dict[str, Any]]:
    return response if isinstance(response, list) else [response]


# ------------------------------------------------------------------ steps
def probe(st: StationSpec, offline: bool) -> dict[str, Any]:
    offsets = [(dy * 0.05, dx * 0.05) for dy in range(-2, 3) for dx in range(-2, 3)]
    lats = ",".join(f"{st.lat + dy:.3f}" for dy, _ in offsets)
    lons = ",".join(f"{st.lon + dx:.3f}" for _, dx in offsets)
    got = _get(
        FLOOD_URL,
        {
            "latitude": lats,
            "longitude": lons,
            "daily": "river_discharge",
            "start_date": PROBE_START.isoformat(),
            "end_date": PROBE_END.isoformat(),
            "cell_selection": "nearest",
            "timezone": "GMT",
        },
        RAW / f"probe_{st.station_id}.json",
        offline,
    )
    best: dict[str, Any] | None = None
    for item in _as_list(got["response"]):
        vals = [v for v in item["daily"]["river_discharge"] if v is not None]
        mean = float(np.mean(vals)) if vals else -1.0
        if best is None or mean > best["mean"]:
            best = {"lat": float(item["latitude"]), "lon": float(item["longitude"]), "mean": mean}
    assert best is not None and best["mean"] > 0, f"no discharge cell found for {st.station_id}"
    log(
        f"  {st.station_id:16s} requested {st.lat:.3f},{st.lon:.3f} -> cell "
        f"{best['lat']:.4f},{best['lon']:.4f} (probe mean {best['mean']:.0f} m3/s)"
    )
    return best


def fetch_discharge(st: StationSpec, cell: dict[str, Any], offline: bool) -> tuple[pd.Series, str]:
    got = _get(
        FLOOD_URL,
        {
            "latitude": f"{cell['lat']:.4f}",
            "longitude": f"{cell['lon']:.4f}",
            "daily": "river_discharge",
            "start_date": FETCH_START.isoformat(),
            "end_date": END.isoformat(),
            "cell_selection": "nearest",
            "timezone": "GMT",
        },
        RAW / f"discharge_{st.station_id}.json",
        offline,
    )
    item = _as_list(got["response"])[0]
    if (
        abs(float(item["latitude"]) - cell["lat"]) > 1e-3
        or abs(float(item["longitude"]) - cell["lon"]) > 1e-3
    ):
        raise SystemExit(f"{st.station_id}: full-series cell differs from the probed cell")
    s = pd.Series(
        item["daily"]["river_discharge"],
        index=pd.to_datetime(item["daily"]["time"]),
        dtype="float64",
        name=st.station_id,
    )
    if s[s.index < pd.Timestamp(START)].notna().any():
        log(f"  note: {st.station_id} has values before {START}; they are not used")
    return s[s.index >= pd.Timestamp(START)], str(got["url"])


def fetch_point(p: PointSpec, offline: bool) -> tuple[pd.DataFrame, dict[str, float], str]:
    got = _get(
        ARCHIVE_URL,
        {
            "latitude": f"{p.lat:.3f}",
            "longitude": f"{p.lon:.3f}",
            "daily": "precipitation_sum,temperature_2m_mean",
            "start_date": FETCH_START.isoformat(),
            "end_date": END.isoformat(),
            "timezone": "GMT",
        },
        RAW / f"era5_{p.point_id}.json",
        offline,
    )
    item = _as_list(got["response"])[0]
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(item["daily"]["time"]),
            "point_id": p.point_id,
            "precip_mm": pd.to_numeric(item["daily"]["precipitation_sum"]),
            "temp_c": pd.to_numeric(item["daily"]["temperature_2m_mean"]),
        }
    )
    df = df[df["date"] >= pd.Timestamp(START)].reset_index(drop=True)
    return df, {"lat": float(item["latitude"]), "lon": float(item["longitude"])}, str(got["url"])


def return_level(series: pd.Series, years: tuple[int, int], period: float = 5.0) -> float:
    """Empirical T-year return level: the (1 - 1/T) Weibull plotting-position quantile of the
    annual maxima of ``years`` (inclusive)."""
    s = series[(series.index.year >= years[0]) & (series.index.year <= years[1])]
    maxima = np.sort(s.groupby(s.index.year).max().to_numpy())
    n = len(maxima)
    p = 1.0 - 1.0 / period
    # Weibull plotting position: F_i = i / (n + 1), i = 1..n; interpolate linearly.
    ranks = np.arange(1, n + 1) / (n + 1)
    return float(np.interp(p, ranks, maxima))


def join_report(s: pd.Series) -> dict[str, Any]:
    """Describe the series around the end of the reanalysis: the jump at the join compared with
    ordinary day-to-day changes, and repeated values (a sign of a splice)."""
    ln = np.log1p(s)
    d = ln.diff().abs()
    base = d[(d.index >= "2012-01-01") & (d.index < "2022-07-01")]
    j = pd.Timestamp(JOIN_DATE)
    window = d[(d.index > j - pd.Timedelta(days=3)) & (d.index <= j + pd.Timedelta(days=3))]
    after = d[(d.index > j) & (d.index <= "2023-12-31")]
    zero_after = int((after == 0).sum())
    zero_before = int((base == 0).sum())
    return {
        "jump_at_join_abs_dlog": round(float(d.loc[j + pd.Timedelta(days=1)]), 5),
        "max_abs_dlog_join_window": round(float(window.max()), 5),
        "p99_abs_dlog_2012_2022": round(float(base.quantile(0.99)), 5),
        "median_abs_dlog_2012_2022": round(float(base.median()), 5),
        "median_abs_dlog_after_join": round(float(after.median()), 5),
        "repeated_days_after_join": zero_after,
        "repeated_days_2012_2022": zero_before,
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="use only the raw cache")
    args = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)

    log("1. cell probing (5x5 offsets at 0.05 deg, cell_selection=nearest)")
    cells = {st.station_id: probe(st, args.offline) for st in STATIONS}
    picked = [(c["lat"], c["lon"]) for c in cells.values()]
    if len(set(picked)) != len(picked):
        raise SystemExit("two stations snapped to the same GloFAS cell; adjust coordinates")

    log("2. discharge (GloFAS v4 via Open-Meteo Flood API, modeled)")
    series: dict[str, pd.Series] = {}
    urls: dict[str, str] = {}
    for st in STATIONS:
        series[st.station_id], urls[st.station_id] = fetch_discharge(
            st, cells[st.station_id], args.offline
        )

    log("3. ERA5 rain and temperature (Open-Meteo Historical Weather API)")
    frames: list[pd.DataFrame] = []
    point_cells: dict[str, dict[str, float]] = {}
    for p in POINTS:
        df, pc, urls[p.point_id] = fetch_point(p, args.offline)
        frames.append(df)
        point_cells[p.point_id] = pc

    log("4. validation")
    full = pd.date_range(START, END, freq="D")
    problems: list[str] = []
    for sid, s in series.items():
        if not s.index.equals(full):
            problems.append(f"{sid}: dates are not the full daily range")
        if s.isna().any():
            problems.append(f"{sid}: {int(s.isna().sum())} missing days")
        if (s < 0).any():
            problems.append(f"{sid}: negative discharge")
    rain = pd.concat(frames, ignore_index=True)
    for pid, g in rain.groupby("point_id"):
        if len(g) != len(full) or g["precip_mm"].isna().any() or g["temp_c"].isna().any():
            problems.append(f"{pid}: ERA5 gaps")
        if (g["precip_mm"] < 0).any():
            problems.append(f"{pid}: negative precipitation")
    continuity: dict[str, Any] = {}
    for sid, s in series.items():
        window = s[
            (s.index >= pd.Timestamp(CONTINUITY[0])) & (s.index <= pd.Timestamp(CONTINUITY[1]))
        ]
        ok = len(window) == (CONTINUITY[1] - CONTINUITY[0]).days + 1 and not window.isna().any()
        continuity[sid] = {"no_gaps_2022_06_to_2023_12": bool(ok), **join_report(s)}
        if not ok:
            problems.append(f"{sid}: continuity check failed for 2022-06-01..2023-12-31")
    if problems:
        for msg in problems:
            log(f"  FAIL {msg}")
        raise SystemExit("validation failed; the demo dataset was not written")
    log("  no gaps, no negatives, 2022-06-01..2023-12-31 continuous for every station")
    for sid, c in continuity.items():
        log(
            f"  join {sid:16s} jump {c['jump_at_join_abs_dlog']:.4f} vs p99 "
            f"{c['p99_abs_dlog_2012_2022']:.4f}; repeated days after "
            f"{c['repeated_days_after_join']}"
        )

    log("5. thresholds (modeled 5-year return level, 1997-2016)")
    thresholds = {sid: return_level(s, THRESHOLD_YEARS) for sid, s in series.items()}

    discharge = pd.concat(
        [
            pd.DataFrame(
                {"date": s.index, "station_id": sid, "discharge_m3s": s.to_numpy(np.float32)}
            )
            for sid, s in series.items()
        ],
        ignore_index=True,
    )
    discharge["date"] = discharge["date"].dt.date
    discharge = discharge.sort_values(["station_id", "date"]).reset_index(drop=True)
    discharge["station_id"] = discharge["station_id"].astype("string")
    rain["date"] = rain["date"].dt.date
    rain["precip_mm"] = rain["precip_mm"].astype(np.float32)
    rain["temp_c"] = rain["temp_c"].astype(np.float32)
    rain["point_id"] = rain["point_id"].astype("string")
    rain = rain.sort_values(["point_id", "date"]).reset_index(drop=True)

    dpath, rpath = OUT / "discharge_daily.parquet", OUT / "rain_daily.parquet"
    kw: dict[str, Any] = {"index": False, "compression": "zstd", "compression_level": 19}
    discharge.to_parquet(dpath, **kw)
    rain.to_parquet(rpath, **kw)

    stations_out = []
    for st in STATIONS:
        c = cells[st.station_id]
        stations_out.append(
            {
                "station_id": st.station_id,
                "name": st.name,
                "river": st.river,
                "label": f"GloFAS grid cell nearest to {st.name}",
                "requested_lat": st.lat,
                "requested_lon": st.lon,
                "cell_lat": round(c["lat"], 6),
                "cell_lon": round(c["lon"], 6),
                "role": st.role,
                "upstream": list(st.upstream),
                "danger_threshold_m3s": round(thresholds[st.station_id], 1),
                "threshold_method": "modeled_5yr_return_level",
                "published_warning_cusecs": None,
                "note": st.note,
            }
        )
    meta = {
        "dataset": "oracle-demo",
        "built_at": _now(),
        "start": START.isoformat(),
        "end": END.isoformat(),
        "target_kind": "modeled_glofas",
        "stations": stations_out,
        "points": [
            {
                "point_id": p.point_id,
                "name": p.name,
                "kind": p.kind,
                "requested_lat": p.lat,
                "requested_lon": p.lon,
                "cell_lat": point_cells[p.point_id]["lat"],
                "cell_lon": point_cells[p.point_id]["lon"],
            }
            for p in POINTS
        ],
        "continuity": continuity,
        "sources": urls,
    }
    spath = OUT / "stations.json"
    spath.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8", newline="\n")
    write_manifest(meta, [dpath, rpath, spath], len(discharge), len(rain))
    total = sum(p.stat().st_size for p in (dpath, rpath, spath))
    log(
        f"wrote {dpath.name} {dpath.stat().st_size} B, {rpath.name} {rpath.stat().st_size} B, "
        f"total {total} B"
    )
    if total > 2_000_000:
        raise SystemExit("demo dataset exceeds the 2 MB budget")
    return 0


def write_manifest(meta: dict[str, Any], files: list[Path], n_dis: int, n_rain: int) -> None:
    lines = [
        "# Oracle demo dataset",
        "",
        f"Built by `scripts/build_oracle_demo.py` at {meta['built_at']} (dev time; needs the "
        "network once, raw responses cached in the git-ignored `data/raw/oracle/`). Rebuild: "
        "`uv run python scripts/build_oracle_demo.py` (or `--offline` from the cache).",
        "",
        "The discharge series is **modeled** river discharge from GloFAS v4 via the Open-Meteo "
        "Flood API. It is not a gauge record. Each station is the GloFAS grid cell nearest to the "
        "named place. Rain and temperature are ERA5 reanalysis via the Open-Meteo Historical "
        "Weather API.",
        "",
        "## Files",
        "",
        "| File | Content | Size (bytes) | SHA-256 |",
        "|---|---|---|---|",
    ]
    desc = {
        "discharge_daily.parquet": f"`date, station_id, discharge_m3s` (float32), {n_dis} rows",
        "rain_daily.parquet": f"`date, point_id, precip_mm, temp_c` (float32), {n_rain} rows",
        "stations.json": "station table, ERA5 points, continuity report, request URLs",
    }
    for f in files:
        lines.append(f"| `oracle/{f.name}` | {desc[f.name]} | {f.stat().st_size} | `{sha256(f)}` |")
    lines += [
        "",
        f"Period {meta['start']} to {meta['end']}, daily, dates in GMT.",
        "",
        "## Sources and license",
        "",
        "| Source | License | Notes |",
        "|---|---|---|",
        "| Open-Meteo Flood API (`flood-api.open-meteo.com/v1/flood`), GloFAS v4 river discharge "
        '(Copernicus Emergency Management Service, ECMWF) | CC BY 4.0, attribution "Weather data '
        'by Open-Meteo.com"; free non-commercial tier | modeled, 0.05 degree grid |',
        "| Open-Meteo Historical Weather API (`archive-api.open-meteo.com/v1/archive`), ERA5 "
        "(Copernicus Climate Change Service) | CC BY 4.0 (Open-Meteo); ERA5 under the Copernicus "
        "licence | reanalysis |",
        "",
        "## Stations (GloFAS grid cells, chosen by probing; owner review pending)",
        "",
        "| station_id | Label | Role | Requested lat, lon | Cell lat, lon | Danger threshold "
        "(m3/s, assumption) |",
        "|---|---|---|---|---|---|",
    ]
    for s in meta["stations"]:
        lines.append(
            f"| `{s['station_id']}` | {s['label']} | {s['role']} | {s['requested_lat']}, "
            f"{s['requested_lon']} | {s['cell_lat']}, {s['cell_lon']} | "
            f"{s['danger_threshold_m3s']} |"
        )
    lines += [
        "",
        "Danger thresholds are the modeled 5-year return level (Weibull plotting position over "
        "the annual maxima of 1997 to 2016). They are an assumption, not official warning levels.",
        "",
        "## ERA5 points",
        "",
        "| point_id | Name | Kind | Requested lat, lon | Grid lat, lon |",
        "|---|---|---|---|---|",
    ]
    for p in meta["points"]:
        lines.append(
            f"| `{p['point_id']}` | {p['name']} | {p['kind']} | {p['requested_lat']}, "
            f"{p['requested_lon']} | {p['cell_lat']}, {p['cell_lon']} |"
        )
    lines += [
        "",
        "## Continuity after the GloFAS reanalysis period",
        "",
        "Open-Meteo documents the GloFAS v4 reanalysis up to July 2022 and forecast-based values "
        "after it. The build asserts no gaps in 2022-06-01..2023-12-31 and reports the day-to-day "
        "change in ln(Q+1) at the join (2022-07-31 to 2022-08-01) against the 99th percentile of "
        "2012-2022 changes, and the count of days with an unchanged value (a splice sign).",
        "",
        "| station_id | No gaps | Jump at join | p99 2012-2022 | Repeated days after join | "
        "Repeated days 2012-2022 |",
        "|---|---|---|---|---|---|",
    ]
    for sid, c in meta["continuity"].items():
        lines.append(
            f"| `{sid}` | {c['no_gaps_2022_06_to_2023_12']} | {c['jump_at_join_abs_dlog']} | "
            f"{c['p99_abs_dlog_2012_2022']} | {c['repeated_days_after_join']} | "
            f"{c['repeated_days_2012_2022']} |"
        )
    lines.append("")
    (OUT / "MANIFEST.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    sys.exit(main())
