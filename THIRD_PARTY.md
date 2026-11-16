# THIRD_PARTY

Every third-party library, dataset, and model used by Stitch is listed here with its license and how it is used. This file is updated in the same commit that introduces the dependency. Status: `planned` until the code using it lands.

## Datasets

| Name | Used by | License / terms | Status |
|---|---|---|---|
| Sen1Floods11 (Cloud to Street / Bonafilia et al.) | eyes | CC BY 4.0 | planned |
| Open-Meteo forecast + flood APIs | oracle, brain (live mode) | CC BY 4.0 (non-commercial free tier) | planned |
| ERA5 (Copernicus C3S) | oracle | Copernicus licence | planned |
| GloFAS modeled discharge via Open-Meteo flood API (the Oracle target, always labeled "modeled") | oracle | CC BY 4.0 (Open-Meteo) / Copernicus | planned |
| Public gauge readings, Indus at Guddu/Sukkur/Kotri (optional small validation set) | oracle eval | TBD, included only if redistributable | planned |
| Sentinel-1 scene of Sindh, Aug 2022 (one clipped scene, demo only) | eyes | Copernicus Sentinel data terms (free, full, open); attribution required | planned |
| UNOSAT / Copernicus EMS Sindh 2022 reference extent (qualitative overlay) | eyes | TBD, included only if redistributable | planned |
| WorldPop Global 2000-2020 1 km, Pakistan 2020 (`pak_ppp_2020_1km_Aggregated`), district sums in `data/demo/ledger/districts.parquet` | ledger | CC BY 4.0, attribution: www.worldpop.org | in use |
| OpenStreetMap roads (motorway to tertiary, via Overpass API), clipped length per district in `districts.parquet` | ledger | ODbL 1.0, (c) OpenStreetMap contributors | in use |
| geoBoundaries gbOpen PAK ADM2, 2019 (Runfola et al. 2020, www.geoboundaries.org), simplified Sindh subset in `data/demo/boundaries/pk_districts.geojson` (shared with eyes) | ledger, eyes | CC BY 4.0 (site statement; per-boundary metadata says Public Domain) | in use |
| NDMA / PDMA publications | library | public documents; verify per-document terms | planned |
| ReliefWeb reports | library | per-report terms; API terms of use | planned |
| Sphere Handbook | library | CC BY-NC-SA / check edition | planned |

## Models

| Name | Used by | License | Status |
|---|---|---|---|
| SegFormer / U-Net backbone weights (TBD) | eyes | TBD | planned |
| Embedding model (TBD, multilingual) | library | TBD | planned |
| Reranker model (TBD) | library | TBD | planned |
| Whisper `tiny` / `base` (size set by `STITCH_WHISPER_MODEL`) | voice | MIT | planned |
| Azure Neural TTS (default; `ur-PK-UzmaNeural`) | voice | Microsoft service terms. Generated audio is committed only if the terms allow | planned |
| Google Cloud Text-to-Speech (fallback provider) | voice | Google service terms | planned |
| Meta MMS-TTS (optional local mode, OFF by default, not bundled) | voice | CC BY-NC 4.0 (non-commercial) | optional |
| Coqui XTTS (not used; noted as a non-commercial alternative) | voice | CPML (non-commercial) | not used |

## Code libraries

Python: FastAPI, MCP Python SDK, Pydantic v2, PyTorch, ONNX Runtime, scikit-learn, rasterio, geopandas, DuckDB, OR-Tools / PuLP, Hypothesis, pytest, psycopg, pgvector. Frontend: Next.js, React, Tailwind CSS, Framer Motion, MapLibre GL, Playwright. Infra: Caddy, Docker, Postgres. Exact versions are pinned in `uv.lock` and `package-lock.json`.

Bootstrap tooling (added with the bootstrap spec; versions pinned in `uv.lock`):
| Library | Used by | License | Status |
|---|---|---|---|
| uv | workspace, lockfile | MIT / Apache-2.0 | in use |
| Pydantic v2 | stitch_common | MIT | in use |
| pytest, pytest-asyncio | tests | MIT | in use |
| Hypothesis | property tests | MPL-2.0 | in use |
| jsonschema | schema round-trip tests | MIT | in use |
| PyYAML | parse agent front matter in tests | MIT | in use |
| ruff, mypy | lint, type-check | MIT | in use |
| MCP Python SDK (`mcp`) | organ template and its smoke test | MIT | in use |
| hatchling | build backend for workspace packages | MIT | in use |
## Generated / AI-assisted code

Specs, steering docs, and code are developed with Kiro (AI-assisted). See `docs/kiro-writeup.md`.

## Library corpus (per document)

Only documents with `redistributable = true` are committed. The rest are fetched by `scripts/fetch_corpus.py` and never committed. One row per document is added when the document is added (full detail in `data/demo/MANIFEST.md`).

| Document | Publisher | License / terms | Redistributable | Committed |
|---|---|---|---|---|
| (none yet) | | | | |

## Training compute (no third-party code)
Training runs on Google Colab (free) and Modal. These are services, not redistributed code.
## ledger-mcp code libraries
Added by `scripts/scaffold_organ.py`. List every library this organ adds beyond the workspace baseline (stitch-common, MCP SDK, pytest, Hypothesis) in the same commit that adds it.
| Library | Used for | License | Status |
|---|---|---|---|
| OR-Tools (GLOP, SCIP via `pywraplp`) | LP/MIP allocation solver | Apache-2.0 (SCIP bundled under Apache-2.0 since SCIP 9) | in use |
| DuckDB | RunStore (run results for `sensitivity_report`) | MIT | in use |
| PyArrow | read the committed district Parquet | Apache-2.0 | in use |
| rasterio, shapely (dev-time only, `uv run --with`, not a workspace dependency) | `scripts/build_ledger_demo.py`: raster sums and road clipping | BSD-3-Clause, BSD-3-Clause | in use (build script) |
| NumPy, pandas, protobuf, absl-py | transitive dependencies of OR-Tools | BSD-3-Clause, BSD-3-Clause, BSD-3-Clause, Apache-2.0 | in use (transitive) |

## frontend code libraries and fonts
npm packages (versions pinned in `frontend/package-lock.json`). Runtime packages ship in the browser bundle; dev packages do not.
| Library | Used for | License | Status |
|---|---|---|---|
| Next.js | static-export app framework | MIT | in use (runtime) |
| React, React DOM | UI | MIT | in use (runtime) |
| Motion (`motion`, formerly Framer Motion) | `LazyMotion` jar and card animation | MIT | in use (runtime) |
| MapLibre GL JS | haunted map (lazy chunk) | BSD-3-Clause | in use (runtime, lazy) |
| Tailwind CSS, `@tailwindcss/postcss`, PostCSS | styling | MIT | in use (build) |
| TypeScript | type-check | Apache-2.0 | in use (dev) |
| ESLint, eslint-config-next, `@eslint/eslintrc` | lint | MIT | in use (dev) |
| Vitest, `@vitejs/plugin-react`, jsdom | unit and component tests | MIT | in use (dev) |
| Testing Library (`@testing-library/react`, `jest-dom`, `user-event`) | component tests | MIT | in use (dev) |
| fast-check | property tests (FRN-P1 to P7) | MIT | in use (dev) |
| Playwright (`@playwright/test`) | UI smoke tests | Apache-2.0 | in use (dev) |
| axe-core, `@axe-core/playwright` | accessibility scan | MPL-2.0 | in use (dev) |
| Ajv, ajv-formats | validate fixtures against the exported JSON Schemas | MIT | in use (dev) |
| json-schema-to-typescript | generate `src/gen/contracts.ts` | MIT | in use (dev) |
| `@types/node`, `@types/react`, `@types/react-dom` | typings | MIT | in use (dev) |
Fonts (self-hosted woff2 in `frontend/public/fonts`, taken from the Fontsource packages built from the upstream releases; license texts are saved next to the files):
| Font | Used for | License | Source |
|---|---|---|---|
| Cinzel (latin 400, 700) | display headings | SIL OFL 1.1 | github.com/NDISCOVER/Cinzel via `@fontsource/cinzel` 5.3.0 |
| Noto Sans (latin 400, 700) | body text, numerals | SIL OFL 1.1 | github.com/notofonts/latin-greek-cyrillic via `@fontsource/noto-sans` 5.3.0 |
| Noto Nastaliq Urdu (arabic 400, 700) | Urdu display text | SIL OFL 1.1 | github.com/notofonts/nastaliq via `@fontsource/noto-nastaliq-urdu` 5.3.0 |
| Noto Naskh Arabic (arabic 400, 700) | Urdu body text | SIL OFL 1.1 | github.com/notofonts/arabic via `@fontsource/noto-naskh-arabic` 5.3.0 |
Frontend sounds are synthesized at runtime with Web Audio; there are no audio files. Map geometry in `frontend/public/map/` is a labelled placeholder until `data/demo/boundaries/pk_districts.geojson` lands (see `docs/decisions.md`).
## brain code libraries
Libraries the Brain (rain/, package stitch_brain) adds beyond the workspace baseline.
| Library | Used for | License | Status |
|---|---|---|---|
| FastAPI (and Starlette, its ASGI toolkit) | Brain HTTP/SSE API | MIT, BSD-3-Clause | in use |
| Uvicorn | ASGI server for the Brain | BSD-3-Clause | in use |
| DuckDB | Brain RunStore (runs, events, evidence, traces) | MIT | in use |
| PyYAML | Brain config files (scenarios, organs, conflict rules, i18n) | MIT | in use |
| MCP Python SDK client (mcp.Client, stdio and streamable HTTP) | Brain to organ calls | MIT | in use |