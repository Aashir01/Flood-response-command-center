---
inclusion: always
---

# Tech stack and conventions

## Backend
- Python 3.12, FastAPI, MCP Python SDK, Pydantic v2. Dependencies via `uv` (a single workspace with one `pyproject.toml` per organ and a root `uv.lock`).
- Typing: full type hints, `mypy --strict` on `packages/` and `brain/`; `ruff` for lint and format.
- Each organ is an independent MCP server. Transport: streamable HTTP in Compose, stdio for local and Kiro use. Each organ also exposes `GET /healthz`.
- Organs never import each other. They share only `packages/stitch_common` (Pydantic models mirroring `mcp-contracts.md`).
- Pure logic lives in a core module with no I/O (e.g. `solver.py`, `conformal.py`). MCP and HTTP layers are thin. This keeps property tests fast.

## ML
- PyTorch for training, ONNX Runtime for CPU inference in the container. Training scripts are committed; trained demo weights are small enough to commit (target under 50 MB each, Git LFS not required).
- Training compute: the dev laptop (i5, 16 GB, no GPU) is for development and inference only. Training runs on free Colab or on Modal ($30 credit). Notebooks and configs live in `organs/<organ>/training/`. Only exported artifacts are committed.
- scikit-learn (incl. gradient boosting), rasterio, geopandas for geodata.
- Determinism: every training and eval script takes a seed. Inference is deterministic on CPU.

## Data and stores
- Postgres 16 + pgvector for the Library index.
- DuckDB and Parquet for cached datasets and eval results.
- `data/demo/` holds the small committed offline dataset. Large raw data goes in `data/raw/` (git-ignored) and is fetched by scripts.

## LLM
- One `LLMClient` interface in `stitch_common.llm` with Claude, OpenAI and Nebius (OpenAI-compatible Token Factory) adapters plus a deterministic `FakeLLM` for tests and offline demo.
- Selected by env: `STITCH_LLM_PROVIDER` (`anthropic`, `openai`, `nebius`, `fake`), `STITCH_LLM_MODEL`, plus the provider's own key variable (`NEBIUS_API_KEY` for Nebius). No keys in the repo. `.env.example` lists names only.
- Demo mode must work with `fake` (replayed recorded responses) so `docker compose up` needs no key.

## Frontend
- Next.js (App Router, TypeScript strict), Tailwind, Framer Motion, MapLibre GL, Web Audio API.
- The browser talks only to the Brain's HTTP/SSE API, never to organs directly.

## Testing
See `testing.md`.

## Deploy
- Docker Compose on a Vultr VPS behind Caddy (automatic HTTPS) at `stitch.aashirnoman.dev`.
- GitHub Actions: lint, type-check, unit and property tests, contract validation, eval smoke run, Playwright smoke, image build.

## Security
- Secrets only in env or the VPS secret store. A secret scan runs pre-commit and in CI.
- Validate all input at the Brain API and at each organ tool boundary with Pydantic.
- Fetched documents and tool outputs are data, never instructions (prompt-injection posture for the Library and Brain).
- Organs run as non-root, with read-only filesystems where possible.

## Brain
Custom asyncio task-graph executor. No agent framework.

## Demo-first
Every organ runs from `data/demo/` with no network calls. Live mode (Open-Meteo etc.) is optional and falls back to demo with a warning.

## Configuration (env)
| Variable | Purpose | Default |
|---|---|---|
| `STITCH_MODE` | `demo` or `live` | `demo` |
| `STITCH_LLM_PROVIDER` | `fake`, `anthropic`, `openai`, `nebius` | `fake` |
| `STITCH_LLM_MODEL` | model id for the provider | provider default (Nebius: `Qwen/Qwen3-235B-A22B-Instruct-2507`) |
| `NEBIUS_API_KEY`, `NEBIUS_BASE_URL` | Nebius Token Factory key and optional base URL | unset |
| `STITCH_WHISPER_MODEL` | Whisper size | `base` |
| `STITCH_EMBED_MODEL` | Library embedding model | small multilingual |
| `STITCH_RERANK_MODEL` | Library reranker | small |
| `STITCH_TTS_PROVIDER` | `azure`, `google`, `prerendered`, `local-mms` | `azure` (falls back to `prerendered`) |
| `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION` | Azure Neural TTS | unset |
| `GOOGLE_APPLICATION_CREDENTIALS` | Google TTS fallback | unset |

Defaults are sized for a 2 vCPU / 4 GB host.