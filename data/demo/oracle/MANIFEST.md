# Oracle demo dataset

Built by `scripts/build_oracle_demo.py` at 2026-11-16T20:39:09Z (dev time; needs the network once, raw responses cached in the git-ignored `data/raw/oracle/`). Rebuild: `uv run python scripts/build_oracle_demo.py` (or `--offline` from the cache).

The discharge series is **modeled** river discharge from GloFAS v4 via the Open-Meteo Flood API. It is not a gauge record. Each station is the GloFAS grid cell nearest to the named place. Rain and temperature are ERA5 reanalysis via the Open-Meteo Historical Weather API.

## Files

| File | Content | Size (bytes) | SHA-256 |
|---|---|---|---|
| `oracle/discharge_daily.parquet` | `date, station_id, discharge_m3s` (float32), 69027 rows | 237556 | `c887b8aae3b3caa2ba2bbb1508ac5f1f78b0e710fbba690c9d3f9ab34a8e7e57` |
| `oracle/rain_daily.parquet` | `date, point_id, precip_mm, temp_c` (float32), 49305 rows | 191754 | `3df57a1a7d27d5b047b40966193a98a8ee3a15ab0b025b85e0a8b016bcd90b80` |
| `oracle/stations.json` | station table, ERA5 points, continuity report, request URLs | 10130 | `47b5bfb66f8815763117bd4a4775442d548bb39367a806cdd564fa01ede3c971` |

Period 1997-01-01 to 2023-12-31, daily, dates in GMT.

## Sources and license

| Source | License | Notes |
|---|---|---|
| Open-Meteo Flood API (`flood-api.open-meteo.com/v1/flood`), GloFAS v4 river discharge (Copernicus Emergency Management Service, ECMWF) | CC BY 4.0, attribution "Weather data by Open-Meteo.com"; free non-commercial tier | modeled, 0.05 degree grid |
| Open-Meteo Historical Weather API (`archive-api.open-meteo.com/v1/archive`), ERA5 (Copernicus Climate Change Service) | CC BY 4.0 (Open-Meteo); ERA5 under the Copernicus licence | reanalysis |

## Stations (GloFAS grid cells, chosen by probing; owner review pending)

| station_id | Label | Role | Requested lat, lon | Cell lat, lon | Danger threshold (m3/s, assumption) |
|---|---|---|---|---|---|
| `indus-kalabagh` | GloFAS grid cell nearest to Indus near Kalabagh | feature | 32.96, 71.55 | 32.925003, 71.425 | 16128.7 |
| `kabul-nowshera` | GloFAS grid cell nearest to Kabul near Nowshera | feature | 34.0, 71.98 | 34.025, 72.02501 | 2327.6 |
| `chenab-trimmu` | GloFAS grid cell nearest to Chenab near Trimmu | forecast | 31.15, 72.15 | 31.175003, 72.07501 | 5679.2 |
| `indus-taunsa` | GloFAS grid cell nearest to Indus near Taunsa | forecast | 30.51, 70.85 | 30.575005, 70.77501 | 16061.3 |
| `indus-guddu` | GloFAS grid cell nearest to Indus near Guddu | forecast | 28.42, 69.72 | 28.525002, 69.82501 | 21085.2 |
| `indus-sukkur` | GloFAS grid cell nearest to Indus near Sukkur | forecast | 27.69, 68.85 | 27.775002, 68.875015 | 20931.2 |
| `indus-kotri` | GloFAS grid cell nearest to Indus near Kotri | forecast | 25.37, 68.31 | 25.475006, 68.27501 | 20575.2 |

Danger thresholds are the modeled 5-year return level (Weibull plotting position over the annual maxima of 1997 to 2016). They are an assumption, not official warning levels.

## ERA5 points

| point_id | Name | Kind | Requested lat, lon | Grid lat, lon |
|---|---|---|---|---|
| `rain-swat` | Swat / lower Kabul basin | rain | 34.8, 72.3 | 34.83304, 72.31939 |
| `rain-jhelum` | Upper Jhelum (Muzaffarabad) | rain | 34.3, 73.7 | 34.27065, 73.851944 |
| `rain-chenab` | Chenab foothills (Jammu) | rain | 32.9, 74.9 | 32.864674, 74.9082 |
| `rain-sulaiman` | Sulaiman range hill torrents | rain | 30.3, 69.8 | 30.263618, 69.76581 |
| `temp-gilgit` | Upper Indus (Gilgit), snowmelt proxy | temp | 35.9, 74.3 | 35.95782, 74.28201 |

## Continuity after the GloFAS reanalysis period

Open-Meteo documents the GloFAS v4 reanalysis up to July 2022 and forecast-based values after it. The build asserts no gaps in 2022-06-01..2023-12-31 and reports the day-to-day change in ln(Q+1) at the join (2022-07-31 to 2022-08-01) against the 99th percentile of 2012-2022 changes, and the count of days with an unchanged value (a splice sign).

| station_id | No gaps | Jump at join | p99 2012-2022 | Repeated days after join | Repeated days 2012-2022 |
|---|---|---|---|---|---|
| `indus-kalabagh` | True | 0.0023 | 0.22029 | 7 | 98 |
| `kabul-nowshera` | True | 0.0 | 0.31237 | 10 | 70 |
| `chenab-trimmu` | True | 0.0 | 0.25484 | 27 | 160 |
| `indus-taunsa` | True | 0.0 | 0.19726 | 5 | 93 |
| `indus-guddu` | True | 0.0 | 0.18421 | 17 | 107 |
| `indus-sukkur` | True | 0.0 | 0.23026 | 17 | 111 |
| `indus-kotri` | True | 0.0 | 0.2794 | 20 | 137 |
