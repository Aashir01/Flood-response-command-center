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
| WorldPop population grids | ledger | CC BY 4.0 | planned |
| OpenStreetMap roads | ledger | ODbL | planned |
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
| NumPy, pandas, protobuf, absl-py | transitive dependencies of OR-Tools | BSD-3-Clause, BSD-3-Clause, BSD-3-Clause, Apache-2.0 | in use (transitive) |
