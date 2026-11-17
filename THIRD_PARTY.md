# THIRD_PARTY

Every third-party library, dataset, and model used by Stitch is listed here with its license and how it is used. This file is updated in the same commit that introduces the dependency. Status: `planned` until the code using it lands.

## Datasets

| Name | Used by | License / terms | Status |
|---|---|---|---|
| Sen1Floods11 (Cloud to Street / Bonafilia et al.) | eyes | CC BY 4.0 | planned |
| Open-Meteo Flood API, Historical Weather API and Forecast API (request URLs in `data/demo/oracle/stations.json`; recorded live responses in `organs/oracle/tests/fixtures/live_openmeteo.json`) | oracle (demo data build, optional live mode, live-mode test fixture), brain (live mode) | CC BY 4.0, attribution "Weather data by Open-Meteo.com"; free non-commercial tier, accepted by the owner for this demo | in use |
| ERA5 reanalysis daily precipitation and mean temperature (Copernicus C3S), via the Open-Meteo Historical Weather API, 5 points, 1997-2023, in `data/demo/oracle/rain_daily.parquet` | oracle | Copernicus licence; CC BY 4.0 via Open-Meteo | in use |
| GloFAS v4 modeled river discharge (Copernicus Emergency Management Service, ECMWF) via the Open-Meteo Flood API, 7 grid cells, 1997-2023, in `data/demo/oracle/discharge_daily.parquet` (the Oracle target, always labeled "modeled") | oracle | CC BY 4.0 (Open-Meteo) / Copernicus | in use |
| Public gauge readings, Indus at Guddu/Sukkur/Kotri (optional small validation set) | oracle eval | none found that are public, redistributable and cheap | not used (the eval reports `observed_validation: "not performed"`) |
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
| OpenAI Python SDK (`openai`) | `stitch_common.llm` OpenAI and Nebius adapters (extra `openai`, installed in Brain and Library) | Apache-2.0 | in use |
| Anthropic Python SDK (`anthropic`) | `stitch_common.llm` Claude adapter (optional extra, not in images) | MIT | optional |
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
## oracle-mcp code libraries
Added by `scripts/scaffold_organ.py`. List every library this organ adds beyond the workspace baseline (stitch-common, MCP SDK, pytest, Hypothesis) in the same commit that adds it.
| Library | Used for | License | Status |
|---|---|---|---|
| LightGBM 4.x | quantile gradient boosting, TreeSHAP contributions (text model files, no pickle) | MIT | in use |
| SciPy (LightGBM dependency) | sparse matrix support inside LightGBM | BSD-3-Clause | in use |
| NumPy | arrays in the pure core | BSD-3-Clause | in use |
| pandas | feature tables, Parquet I/O | BSD-3-Clause | in use |
| pyarrow | Parquet engine for the demo dataset and conformity scores | Apache-2.0 | in use |
| DuckDB | run store for `explain_forecast` | MIT | in use |
| PyYAML | read `training/config.yaml` | MIT | in use (training only) |
| PyTorch | stretch quantile MLP comparison (`training/train_mlp.py`), run with `uv run --with torch`; not a project dependency, not shipped | BSD-3-Clause | dev-time only |
## library-mcp code libraries
Added by `scripts/scaffold_organ.py`. List every library this organ adds beyond the workspace baseline (stitch-common, MCP SDK, pytest, Hypothesis) in the same commit that adds it. Licenses below were read from the installed package metadata (`importlib.metadata`) on 2026-11-17.
| Library | Used for | License | Status |
|---|---|---|---|
| NumPy | vectors, dense search in `MemoryStore` | BSD-3-Clause (bundled parts 0BSD, MIT, Zlib, CC0-1.0) | in use |
| ONNX Runtime | CPU inference of the embedder and reranker | MIT | in use |
| Hugging Face `tokenizers` | tokenization without PyTorch or `transformers` | Apache-2.0 | in use |
| pypdfium2 (PDFium) | PDF text extraction for fetched documents | BSD-3-Clause or Apache-2.0 (PDFium binaries carry their own notices) | in use |
| pdfminer.six | fallback PDF text extraction | MIT | in use |
| PyArrow | Parquet pack (`pages.parquet`, `chunks.parquet`) | Apache-2.0 | in use |
| PyYAML | manifest, demo questions, scope anchors | MIT | in use |
| psycopg 3 (`psycopg[binary]`) | `PgVectorStore` (Postgres + pgvector) | LGPL-3.0-only, used unmodified as a dynamically loaded library | in use |
| ONNX (`onnx`, extra `export`, dev-time only) | int8 export of the embedding model (`scripts/export_models.py`) | Apache-2.0 | dev-time |
| PyMuPDF | not used: AGPL-3.0 is incompatible with the MIT repo | AGPL-3.0 | rejected |

## brain code libraries
Libraries the Brain (rain/, package stitch_brain) adds beyond the workspace baseline.
| Library | Used for | License | Status |
|---|---|---|---|
| FastAPI (and Starlette, its ASGI toolkit) | Brain HTTP/SSE API | MIT, BSD-3-Clause | in use |
| Uvicorn | ASGI server for the Brain | BSD-3-Clause | in use |
| DuckDB | Brain RunStore (runs, events, evidence, traces) | MIT | in use |
| PyYAML | Brain config files (scenarios, organs, conflict rules, i18n) | MIT | in use |
| MCP Python SDK client (mcp.Client, stdio and streamable HTTP) | Brain to organ calls | MIT | in use |
## eyes-mcp code libraries
Added by `scripts/scaffold_organ.py`. List every library this organ adds beyond the workspace baseline (stitch-common, MCP SDK, pytest, Hypothesis) in the same commit that adds it.
| Library | Used for | License | Status |
|---|---|---|---|
| ONNX Runtime | CPU inference of the shipped U-Net (`organs/eyes/models/eyes_unet_r18.onnx`) | MIT | in use |
| NumPy | tiling, integer blending, masks, areas | BSD-3-Clause | in use |
| rasterio (bundles GDAL) | COG window reads, district rasterization, raster-to-polygon (`features.shapes`) | BSD-3-Clause (GDAL: MIT/X) | in use |
| Shapely (bundles GEOS) | polygon simplification (`coverage_simplify`), validity repair, precision grid | BSD-3-Clause (GEOS: LGPL-2.1, dynamically linked in the wheel) | in use |
| pyproj (bundles PROJ) | UTM 42N / WGS84 transforms | MIT | in use |
| SciPy | 4-connected component labelling (`ndimage.label`) | BSD-3-Clause | in use |
| PyTorch, torchvision (CPU wheels; `train` extra only, never in the runtime image) | fine-tuning and ONNX export (`organs/eyes/training/`) | BSD-3-Clause | in use (training) |
| segmentation-models-pytorch (and its dependencies timm, huggingface_hub, safetensors) | U-Net/ResNet-18 definition (`train` extra) | MIT (timm, huggingface_hub, safetensors: Apache-2.0) | in use (training) |
| onnx, onnxconverter-common | export, fp16 variant, int8 static quantization tooling (`train` extra) | Apache-2.0 / MIT | in use (training) |
| PyYAML | training config (`train` extra) | MIT | in use (training) |
## voice-mcp code libraries
Added by `scripts/scaffold_organ.py`. List every library this organ adds beyond the workspace baseline (stitch-common, MCP SDK, pytest, Hypothesis) in the same commit that adds it.
| Library | Used for | License | Status |
|---|---|---|---|
| (none yet) | | | |

## Hosted LLM providers (optional, off by default)

The demo runs with `STITCH_LLM_PROVIDER=fake` (recorded replies, no network). Live phrasing, Urdu translation and Library answers can use a hosted provider; keys come only from the environment.

| Service | Used for | Terms | Status |
|---|---|---|---|
| Nebius Token Factory (OpenAI-compatible API, `https://api.tokenfactory.nebius.com/v1/`) | Brain prose and translation, Library answers when `STITCH_LLM_PROVIDER=nebius` | Nebius service terms; model licenses per model card (default `Qwen/Qwen3-235B-A22B-Instruct-2507`, Apache-2.0) | optional |
| Anthropic API, OpenAI API | same, alternative providers | provider service terms | optional |
