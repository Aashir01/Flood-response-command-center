# THIRD_PARTY

Every third-party library, dataset, and model used by Stitch is listed here with its license and how it is used. This file is updated in the same commit that introduces the dependency. Status: `planned` until the code using it lands.

## Datasets

| Name | Used by | License / terms | Status |
|---|---|---|---|
| Sen1Floods11 (Cloud to Street / Bonafilia et al.) | eyes | CC BY 4.0 | planned |
| Open-Meteo forecast + flood APIs | oracle, brain (live mode) | CC BY 4.0 (non-commercial free tier) | planned |
| ERA5 (Copernicus C3S) | oracle | Copernicus licence | planned |
| River gauge data (source TBD, see open questions) | oracle | TBD | planned |
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
| Whisper (size TBD) | voice | MIT | planned |
| TTS model (TBD, Urdu capable) | voice | TBD | planned |

## Code libraries

Python: FastAPI, MCP Python SDK, Pydantic v2, PyTorch, ONNX Runtime, scikit-learn, rasterio, geopandas, DuckDB, OR-Tools / PuLP, Hypothesis, pytest, psycopg, pgvector. Frontend: Next.js, React, Tailwind CSS, Framer Motion, MapLibre GL, Playwright. Infra: Caddy, Docker, Postgres. Exact versions are pinned in `uv.lock` and `package-lock.json`.

## Generated / AI-assisted code

Specs, steering docs, and code are developed with Kiro (AI-assisted). See `docs/kiro-writeup.md`.
