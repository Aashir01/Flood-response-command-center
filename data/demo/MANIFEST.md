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

<!-- library-corpus:begin (generated by scripts/check_corpus_licenses.py) -->
## Library corpus (library-mcp)

Generated from `data/demo/library/manifest.yaml`. Only `tier: committed` documents are in the
repo; `tier: fetch` documents are downloaded by `scripts/fetch_corpus.py` into the git-ignored
`data/raw/library/`. Committed English documents are text renditions of US federal web pages
(public domain under 17 U.S.C. 105); committed Urdu documents are unofficial translations by
the Stitch team (CC BY 4.0), pending a native-speaker review. `owner_confirmed: false` means
the license evidence was checked by the implementing agent, not yet by the owner.

| doc_id | Title | Publisher | Lang | License | Redistributable | Tier | Owner confirmed | Source | License evidence |
|---|---|---|---|---|---|---|---|---|---|
| `fema-ready-water` | Water (Ready.gov) | FEMA | en | US-Gov-PD | yes | committed | no | https://www.ready.gov/water | Ready.gov is a US federal government website run by FEMA (US Department of Homeland Security). Works of the US federal government are not subject to copyright in the US (17 U.S.C. 105). The page text retrieved on 2026-11-17 carried no copyright notice or third-party credit for the text. Images were not copied. |
| `fema-ready-food` | Food (Ready.gov) | FEMA | en | US-Gov-PD | yes | committed | no | https://www.ready.gov/food | US federal government website (FEMA); 17 U.S.C. 105. No copyright notice on the page text retrieved on 2026-11-17. |
| `fema-ready-shelter` | Shelter (Ready.gov) | FEMA | en | US-Gov-PD | yes | committed | no | https://www.ready.gov/shelter | US federal government website (FEMA); 17 U.S.C. 105. No copyright notice on the page text retrieved on 2026-11-17. |
| `fema-ready-floods` | Floods (Ready.gov) | FEMA | en | US-Gov-PD | yes | committed | no | https://www.ready.gov/floods | US federal government website (FEMA); 17 U.S.C. 105. No copyright notice on the page text retrieved on 2026-11-17. The phrase "Turn Around Don't Drown" is a NOAA/NWS registered trademark; it appears only as quoted safety advice. |
| `fema-ready-kit` | Build A Kit (Ready.gov) | FEMA | en | US-Gov-PD | yes | committed | no | https://www.ready.gov/kit | US federal government website (FEMA); 17 U.S.C. 105. No copyright notice on the page text retrieved on 2026-11-17. |
| `epa-emergency-disinfection` | Emergency Disinfection of Drinking Water (US EPA) | US EPA | en | US-Gov-PD | yes | committed | no | https://www.epa.gov/ground-water-and-drinking-water/emergency-disinfection-drinking-water | US Environmental Protection Agency web page ("Last updated on February 24, 2026"); 17 U.S.C. 105. No copyright notice on the page text retrieved on 2026-11-17. The page cites a WHO technical briefing for one statement; no WHO text is reproduced. |
| `stitch-ur-ready-water` | پانی: Ready.gov کا غیر سرکاری اردو ترجمہ | Stitch team | ur | CC-BY-4.0 | yes | committed | no | https://www.ready.gov/water | Unofficial Urdu translation written for this repository by the implementing agent (AI-assisted) from the public-domain FEMA page; released under CC BY 4.0 by the Stitch team. Not reviewed by a native speaker yet. |
| `stitch-ur-ready-floods` | سیلاب: Ready.gov کا غیر سرکاری اردو ترجمہ | Stitch team | ur | CC-BY-4.0 | yes | committed | no | https://www.ready.gov/floods | Unofficial Urdu translation written for this repository by the implementing agent (AI-assisted) from the public-domain FEMA page; released under CC BY 4.0 by the Stitch team. Not reviewed by a native speaker yet. |
| `stitch-ur-ready-shelter-kit` | پناہ گاہ اور ہنگامی سامان: Ready.gov کا غیر سرکاری اردو ترجمہ | Stitch team | ur | CC-BY-4.0 | yes | committed | no | https://www.ready.gov/shelter | Unofficial Urdu translation written for this repository by the implementing agent (AI-assisted) from the public-domain FEMA pages "Shelter" and "Build A Kit"; released under CC BY 4.0 by the Stitch team. Not reviewed by a native speaker yet. |
| `usaid-fog-v4-food-shelter` | Field Operations Guide for Disaster Assessment and Response, Version 4.0: food rations and shelter (USAID/OFDA) | USAID OFDA | en | US-Gov-PD | yes | committed | no | https://archive.org/download/FieldOperationsGuide2005/FieldOperationsGuide2005.pdf | Field Operations Guide (FOG) Version 4.0, September 2005, by the US Agency for International Development, Office of U.S. Foreign Disaster Assistance, "in cooperation with and produced by the USDA Forest Service" (title page); both are US federal agencies, so the text is a work of the US Government (17 U.S.C. 105). The 389-page PDF (sha256 7227d0ec1f33f2d8c08e856df14b30525b07f2775f094988defd18333aec18a2, downloaded on 2026-11-17) has no copyright notice and no "reprinted with permission" or "adapted from" credit on any page (full-text search), and the Internet Archive item FieldOperationsGuide2005 carries the Public Domain Mark 1.0 (checked with web_fetch on 2026-11-17). The introduction lists sources the authors drew on (UNHCR, WHO, Sphere and others); the excerpted passages are OFDA prose with no quoted third-party text. 17 U.S.C. 105 governs US copyright; it does not address protection abroad. |
| `stitch-ur-usaid-fog-food-shelter` | خوراک کا راشن اور ہنگامی پناہ گاہ: USAID فیلڈ آپریشنز گائیڈ کا غیر سرکاری اردو ترجمہ | Stitch team | ur | CC-BY-4.0 | yes | committed | no | https://archive.org/download/FieldOperationsGuide2005/FieldOperationsGuide2005.pdf | Unofficial Urdu translation written for this repository by the implementing agent (AI-assisted) from the public-domain USAID/OFDA Field Operations Guide excerpt (usaid-fog-v4-food-shelter); released under CC BY 4.0 by the Stitch team. Not reviewed by a native speaker yet. |
| `who-tn09-water-quantity` | Technical note 9: How much water is needed in emergencies (WHO/WEDC) | WHO | en | (c) WHO 2013, all rights reserved | no | fetch | no | https://cdn.who.int/media/docs/default-source/wash-documents/who-tn-09-how-much-water-is-needed.pdf | Page 4 of the PDF reads "(c) World Health Organization 2013. All rights reserved." (read from the downloaded file on 2026-11-17). Not an open license. |
| `sphere-handbook-2018-en` | The Sphere Handbook 2018 (English) | Sphere Association | en | Sphere Association copyright; educational reproduction with acknowledgment | no | fetch | no | https://spherestandards.org/wp-content/uploads/Sphere-Handbook-2018-EN.pdf | The intellectual-property page returned HTTP 403 to scripted requests (spec author and agent, 2026-11-17). A search snippet says the material is copyrighted and may be reproduced for educational purposes with acknowledgment, not for resale. Not an open license. |
| `ndma-plan-2026-07` | NDMA plan document uploaded July 2026 (ndma.gov.pk/plans; owner to confirm the title) | NDMA Pakistan | en | Unclear: no license statement found | no | fetch | no | https://www.ndma.gov.pk/storage/plans/July2026/6a574d2ba18a7.pdf | No license or open-data statement found on ndma.gov.pk. Government works are not automatically public domain under Pakistan's Copyright Ordinance 1962. Treated as not redistributable until NDMA grants written permission. |

<!-- library-corpus:end -->
