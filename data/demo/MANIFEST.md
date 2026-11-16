# Demo data manifest

Every committed file under `data/demo/` is listed here with its source, license, date and how it was made. Other organs append their own sections. Demo data is labelled as demo everywhere it is shown; nothing here is live or operational data.

## Ledger (`demo-sindh-2022`)

Built by `scripts/build_ledger_demo.py` on 2026-11-16 (dev time, needs the network once; raw inputs go to the git-ignored `data/raw/ledger/`). To rebuild: `uv run --with rasterio --with shapely python scripts/build_ledger_demo.py --fetch`.

### Files

| File | Content | Size |
|---|---|---|
| `boundaries/pk_districts.geojson` | 22 Sindh district polygons, simplified (0.003 degrees), 4-decimal coordinates, stable ids `pk-sindh-<slug>`. Shared with the Eyes organ. | 43 KB |
| `ledger/districts.parquet` | One row per district (22 rows). | 5 KB |

### Sources

| Source | Version used | License | Notes |
|---|---|---|---|
| geoBoundaries gbOpen, Pakistan ADM2 (Runfola et al. 2020, www.geoboundaries.org) | boundary year 2019, release commit `9469f09`, simplified geometry; SHA-256 `f274cfc3...566f2e` | CC BY 4.0 per the geoBoundaries site. The per-boundary metadata for PAK ADM2 says "Public Domain". The stricter CC BY 4.0 attribution is applied. | Not GADM. 22 Sindh units chosen by name. Larkana and Sujawal are not separate units in this vintage (Qambar Shahdadkot's population of 3.3 M suggests it contains Larkana's area). The boundaries are 2019 vintage, not current administrative limits. |
| WorldPop, Global 2000-2020 1 km, `pak_ppp_2020_1km_Aggregated.tif` | 2020 estimate (people per 1 km pixel), SHA-256 `d2416912...f7cdbb` | CC BY 4.0 | www.worldpop.org. Pixel values summed where the pixel centre lies inside the district polygon. A modelled estimate, not a census count. |
| OpenStreetMap via Overpass API | database timestamp 2026-11-16T19:42:36Z; 18,611 ways: motorway, trunk, primary, secondary, tertiary | ODbL 1.0 | (c) OpenStreetMap contributors. Dual carriageways are counted twice. Links and unclassified roads are excluded. |

### `districts.parquet` columns

| Column | Kind | Derivation |
|---|---|---|
| `district_id` | key | `pk-sindh-<slug>`, unique, stable |
| `name` | label | geoBoundaries `shapeName`, normalised spelling |
| `province` | label | `Sindh` |
| `population` | **real (modelled)** | WorldPop 2020 1 km sum per district. Total 49.5 M. Not the 2017 census. |
| `road_access` | **real input, proxy output** | OSM road km (primary to tertiary) clipped to the district, divided by district area (Lambert equal-area), divided by the 90th percentile over the 22 districts, clipped to [0, 1]. It measures baseline network density in normal conditions. It is **not** flood-time passability. |
| `alt_delivery_fraction` | **assumption** | 0.05 for Dadu, Jamshoro, Qambar Shahdadkot and Badin; 0 elsewhere. Illustrative share of people that boats or helicopters could carry. Not measured. |
| `default_severity` | **illustrative prior** | Tiers by analyst judgement: 0.9 (Dadu, Jamshoro, Qambar Shahdadkot, Khairpur), 0.75 (Sanghar, Shikarpur, Jacobabad, Badin, Nawabshah, Naushahro Feroze, Mirpur Khas), 0.5 (Sukkur, Kashmore, Ghotki, Tando Allahyar, Tando Muhammad Khan, Matiari, Umerkot, Hyderabad), 0.3 (Tharparkar, Thatta), 0.1 (Karachi). Based on general reporting about the 2022 floods, **not** on district-level PDMA/NDMA figures. Replace it with those when they are available. |
| `area_km2` | derived | polygon area, Lambert cylindrical equal-area |
| `road_km` | derived | clipped OSM road length |

No district has `road_access` below the usable-access threshold (0.1), so the demo scenario by itself has no road-denied or unreachable district. Those paths are exercised by the `districts` override and by tests.

### Limits

Population, road length and area were computed on the geoBoundaries "simplified" geometry. The committed GeoJSON is simplified once more (about 300 m), so overlaying it on those numbers is approximate. Populations are 2020 modelled estimates, before the 2022 displacement. The demo scenario does not describe real 2022 flood extents.
## Oracle (`data/demo/oracle/`)
Built by `scripts/build_oracle_demo.py` (dev time, needs the network once; raw responses go to the git-ignored `data/raw/oracle/`). Full detail, request URLs, grid-cell coordinates, continuity report and SHA-256 of each file: `data/demo/oracle/MANIFEST.md`.
| File | Content | Source | License |
|---|---|---|---|
| `oracle/discharge_daily.parquet` | modeled GloFAS v4 river discharge, 7 grid cells, daily 1997-2023 | Open-Meteo Flood API | CC BY 4.0 (Open-Meteo), GloFAS (Copernicus/ECMWF) |
| `oracle/rain_daily.parquet` | ERA5 daily precipitation and mean temperature, 5 points, daily 1997-2023 | Open-Meteo Historical Weather API | CC BY 4.0 (Open-Meteo), ERA5 (Copernicus C3S) |
| `oracle/stations.json` | station table (GloFAS grid cell nearest to each named place), danger thresholds (modeled 5-year return level, an assumption) | derived | CC BY 4.0 |
| `oracle/MANIFEST.md` | build record | derived | - |
The discharge values are modeled, not gauge records. Demo data, not a live feed.

## Brain recorded fixtures (
ecorded/)
Replayed by the Brain's recorded organs (STITCH_RECORDED_ORGANS, brain design 3.3). Every replayed result is labelled in the briefing (caveat.recorded.<organ>, served_by: recorded, a RECORDED_FIXTURE warning) and the briefing mode is demo.
| Path | Authoring | Content | Source and license |
|---|---|---|---|
| 
ecorded/ledger/** | captured | Real Ledger results (optimize_allocation, sensitivity_report, districts resource) for the exact arguments the Brain sends (match.exact). Written by scripts/record_organ_fixture.py. | Ledger demo dataset above (WorldPop CC BY 4.0, OSM ODbL 1.0, geoBoundaries CC BY 4.0) |
| 
ecorded/eyes/** | hand-authored | Per-district flooded fractions for Sindh, 2022-08-30, chosen by hand to resemble the 2022 pattern; district areas from ledger/districts.parquet; square placeholder shapes marked synthetic. Not a segmentation output. The -conflicts variant maps Thatta as dry on purpose. | Written by scripts/build_brain_fixtures.py, MIT (Stitch); data source id ixture-hand-authored |
| 
ecorded/oracle/** | hand-authored | A seven-day modeled discharge curve, exceedance probabilities and an explanation for the Indus near Kotri. Illustrative values, labelled modeled; the danger threshold is illustrative. | Same script, MIT (Stitch) |
| 
ecorded/library/** | hand-authored | Answers and a refusal paraphrasing well-known Sphere Handbook 2018 minimum standards (15 litres of water and 2,100 kcal per person per day). Quotes are paraphrases and page numbers are not verified. Used in tests and the all-recorded CLI only; the Compose demo uses the real Library. The -conflicts variant states 7.5 litres on purpose (seeded conflict R3). | Same script, MIT (Stitch) |
| llm/brain.jsonl | recorded | FakeLLM replay file for the Brain's phrasing, translation and judge steps. Empty until recorded with a provider key by the owner; the Brain then uses template text. | n/a |