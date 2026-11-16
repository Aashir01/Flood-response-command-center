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
| Hosted TTS API (default; vendor chosen in voice design) | voice | Vendor terms. Generated audio is committed only if terms allow | planned |
| Meta MMS-TTS (optional local mode, OFF by default, not bundled) | voice | CC BY-NC 4.0 (non-commercial) | optional |
| Coqui XTTS (not used; noted as a non-commercial alternative) | voice | CPML (non-commercial) | not used |

## Code libraries

Python: FastAPI, MCP Python SDK, Pydantic v2, PyTorch, ONNX Runtime, scikit-learn, rasterio, geopandas, DuckDB, OR-Tools / PuLP, Hypothesis, pytest, psycopg, pgvector. Frontend: Next.js, React, Tailwind CSS, Framer Motion, MapLibre GL, Playwright. Infra: Caddy, Docker, Postgres. Exact versions are pinned in `uv.lock` and `package-lock.json`.

## Generated / AI-assisted code

Specs, steering docs, and code are developed with Kiro (AI-assisted). See `docs/kiro-writeup.md`.

## Library corpus (per document)

Only documents with `redistributable = true` are committed. The rest are fetched by `scripts/fetch_corpus.py` and never committed. One row per document is added when the document is added (full detail in `data/demo/MANIFEST.md`).

| Document | Publisher | License / terms | Redistributable | Committed |
|---|---|---|---|---|
| (none yet) | | | | |

## Training compute (no third-party code)
Training runs on Google Colab (free) and Modal. These are services, not redistributed code.