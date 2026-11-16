# deployment: Design

Implements `requirements.md` (DEP-R1..R10, DEP-P1..P6). Related: `tech.md` (Deploy, Configuration), `structure.md` (`deploy/`), bootstrap design §8 (CI skeleton), frontend design §2 and §17.

## 1. Overview

One Compose project runs the whole system from committed demo data with no network. A single Caddy-based gateway (`web`) serves the static frontend, proxies `/api/*` to the Brain, and terminates TLS when given a domain. Organs, Postgres, and the Brain live on an **internal-only Docker network with no route to the internet**, which makes the demo-first rule (DEP-R10) a property of the topology instead of a test we hope passes. Live mode and hosted TTS are an opt-in override that adds an egress network to the services that need it.

The owner does not know the Vultr plan size, so the design is built around a **2 vCPU / 4 GB floor** with lazy model loading, small default models, and an explicit "lite" mode that disables the two heaviest organs (Eyes, Voice) without breaking anything else.

Decisions:
1. **One gateway image (`web`) for all environments.** Same Caddyfile in dev, CI, and production; only the site address and published ports differ. CI therefore tests what production runs. (This interprets "Caddy (production profile only)" in DEP-R1.1 as "TLS and public ports only in production". See issue list.)
2. **Internal network for everything but the gateway.** Default Compose has no egress for organs or the Brain.
3. **Secrets are generated on first start into a Docker volume** by a one-shot job, so a clean `docker compose up` works with no `.env` and nothing hardcoded (DEP-R1.1, R3.4).
4. **Deploy by git checkout plus image pull.** The VPS holds a clone of the public repo; CD points it at the released commit and pulls images tagged with the same commit SHA. Rollback is the previous SHA.
5. **Public GHCR images.** The repo is public (MIT) and images contain only demo data, so the VPS pulls with no registry credential.

## 2. Files

```
compose.yaml                         root; `include: [deploy/compose.yaml]` so `docker compose up` works from the repo root
deploy/
  compose.yaml                       base: all services, networks, volumes, healthchecks, limits
  compose.prod.yaml                  production override: ports 80/443, SITE_ADDRESS, Caddyfile.prod, ACME volumes, restart policy
  compose.live.yaml                  live override: adds the `egress` network to brain, oracle, eyes, voice
  compose.lite.yaml                  degraded override: eyes and voice off
  compose.ci.yaml                    CI override: build cache hints only
  docker-bake.hcl                    one build graph for every image, GHA cache, push on demand
  docker/
    organ.Dockerfile                 shared multi-stage Python image (ARG ORGAN)
    brain.Dockerfile
    web.Dockerfile                   node build stage + caddy runtime
    web.placeholder.Dockerfile       Nov 20 dry run image
    postgres/initdb/10-init.sh       extension, roles, grants (reads secrets)
  caddy/
    Caddyfile                        dev and CI (HTTP :8080)
    Caddyfile.prod                   TLS, HSTS, ACME
    snippets/common.caddy            routes, headers, compression, SSE
  env/
    .env.example                     names only
    prod.env.example
  image-budgets.json                 size budgets (§4)
  bin/
    deploy.sh                        forced-command entry on the VPS (§9)
    smoke.py                         HTTP-level smoke, stdlib only (§11)
    check_ports.py, check_images.py, check_repo_hygiene.py
  README.md                          VPS runbook (§10), owner facts, rollback, backup
  placeholder/index.html
.github/workflows/{ci.yml, cd.yml}
```

`structure.md` places `compose.yaml` under `deploy/`. The root file with `include` keeps `docker compose up` working from a clean clone; Compose resolves build contexts and bind mounts in an included file relative to that file. Task 1 verifies this on the installed Compose version; fallback is a root `compose.yaml` that holds the content directly (issue list).

## 3. Compose topology

### 3.1 Services

| Service | Image | Network(s) | Profile | Healthcheck | Depends on (healthy) |
|---|---|---|---|---|---|
| `init-secrets` | `alpine` (pinned) | none | always | one-shot, exits 0 | none |
| `postgres` | `pgvector/pgvector:0.8.x-pg16` (pin exact tag + digest at implementation; the `<pgvector>-pg<major>` tag form exists on Docker Hub, e.g. `0.8.7-pg16`) | core | always | `pg_isready -U stitch_owner -d stitch` | `init-secrets` (completed) |
| `seed` | library image | core | always, one-shot | exits 0 | `postgres` |
| `library` | `stitch-library` | core | always | `GET /healthz` | `seed` (completed) |
| `ledger` | `stitch-ledger` | core | always | `GET /healthz` | none |
| `oracle` | `stitch-oracle` | core | always | `GET /healthz` | none |
| `eyes` | `stitch-eyes` | core | always (off in lite) | `GET /healthz` | none |
| `voice` | `stitch-voice` | core | always (off in lite) | `GET /healthz` | none |
| `brain` | `stitch-brain` | core | always | `GET /healthz` (proposed, see end) | `library`, `ledger`, `oracle`; `eyes` and `voice` with `required: false` |
| `web` | `stitch-web` (Caddy + static export) | edge, core | always | `wget -qO- http://127.0.0.1:8080/healthz` | `brain` |

Notes:
- All images are tagged `ghcr.io/<owner>/stitch-<service>:${TAG:-local}` with a `build:` section, so a clean clone builds locally and the VPS pulls. `<owner>` comes from `GH_OWNER` (default placeholder).
- DEP-R1.5: every dependency uses `condition: service_healthy` (or `service_completed_successfully` for one-shots). `required: false` is Compose's way to tolerate an absent optional dependency (for `lite`); whether an *unhealthy but present* optional service still blocks the Brain's start must be verified on the pinned Compose version in task 6. Fallback: the Brain depends only on the three core organs and retries the others itself (BRN-R1.4 already requires this).
- The Brain is allowed to start while an organ is unhealthy by design in the application (BRN-R1.4), but Compose still gates start on health for a deterministic first boot. `lite` removes the Eyes and Voice dependencies by override.
- Healthchecks for Python images use the interpreter (no curl in slim images): `python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"`, interval 10 s, timeout 5 s, retries 5, `start_period` 20 s (brain, ledger, oracle), 60 s (library, eyes, voice).
- `restart: unless-stopped` for long-running services; none for one-shots.
- No service except `web` has a `ports:` entry. DEP-P4 is enforced by `check_ports.py` (§12).

### 3.2 Networks

| Network | Type | Members | Purpose |
|---|---|---|---|
| `core` | `internal: true` | every service | service-to-service traffic. **No internet route.** |
| `edge` | bridge (normal) | `web` only | publishes ports; gives the gateway outbound access for ACME certificate issuance |
| `egress` | bridge (normal) | none by default; `compose.live.yaml` adds `brain`, `oracle`, `eyes`, `voice` | live mode (Open-Meteo, LLM API, Azure TTS) |

`web` is the only service that can both receive traffic from the internet and reach the organs. Because the organs are on an `internal: true` network, DEP-R4.2 and DEP-R10.1 hold even if someone adds a `ports:` entry by mistake (an internal network cannot publish to the host; `check_ports.py` still fails the build first).

### 3.3 Volumes

| Volume | Mounted in | Notes |
|---|---|---|
| `secrets` | `init-secrets` (rw); postgres, seed, library, brain, voice (ro) | generated passwords, file mode 0444 inside the volume; the volume is not exposed to the host or other containers |
| `pgdata` | postgres | named volume `stitch_pgdata`; the only state worth backing up |
| `caddy_data`, `caddy_config` | web (prod) | **must persist**: certificates and ACME account; losing them risks Let's Encrypt rate limits |
| `voice_cache` | voice (rw) | TTS audio cache, monthly character-budget SQLite file, and (if Azure audio cannot be committed) audio pre-rendered on the VPS; small (cache cap 100 MB) |
| none for models or demo data | | baked into images so nothing is fetched at runtime |

### 3.4 Resource budget (2 vCPU / 4 GiB floor)

Limits are hard ceilings (`deploy.resources.limits`, works in plain Compose v2): an OOM kill hits the offender, not the host. The sum of limits must fit in the host minus OS, Docker, and page cache. Assume **600 MiB reserved** for Ubuntu, dockerd, containerd, sshd, and Caddy's TLS state, leaving **3496 MiB**.

| Service | Idle target (lazy) | Peak target | Memory limit | CPU cap | Notes |
|---|---|---|---|---|---|
| postgres | 90 MiB | 300 MiB | 384 MiB | 0.5 | `shared_buffers=96MB`, `max_connections=30`, `work_mem=4MB`, `shm_size: 128m` |
| brain | 120 | 250 | 320 | 0.5 | asyncio; one process |
| ledger | 100 | 250 | 256 | 1.0 | OR-Tools; `threads=1` |
| oracle | 150 | 300 | 320 | 0.5 | scikit-learn or ONNX gradient boosting |
| library | 150 | 800 | 832 | 1.0 | embedding model resident after first use, reranker loaded on demand |
| eyes | 100 | 600 | 640 | 1.5 | ONNX U-Net; model loaded on first call, unloaded after 120 s idle |
| voice | 100 | 600 | 640 | 1.5 | Whisper `base` int8; loaded on first call, unloaded after 300 s idle |
| web | 25 | 40 | 48 | 0.25 | |
| **Sum** | **835** | **3140** | **3440** | n/a | |

Sum of limits 3440 MiB ≤ 3496 MiB. `seed` and `init-secrets` run before the other services peak and are not additive (limit 512 MiB for `seed`, 32 MiB for `init-secrets`).

**All numbers are design targets, not measurements.** Task 6 measures each service with `docker stats` during the demo briefing and updates this table; any service whose measured peak exceeds its limit forces a smaller default model, not a bigger limit.

Honest note: at simultaneous peaks (Eyes segmenting, Library reranking, Voice transcribing) the host is at the edge, so:
- Models are **lazy-loaded** on first tool call (`STITCH_LAZY_LOAD=1`, default in Compose) and heavy ones unloaded when idle (`STITCH_IDLE_UNLOAD_S`: Eyes 120, Voice 300, Library reranker 300). Idle RSS stays near the idle column.
- The host gets a 2 GiB swapfile as a safety net (runbook §10), not as a plan.
- CPU: `OMP_NUM_THREADS=2`, ONNX Runtime `intra_op_num_threads=2`, CTranslate2 `cpu_threads=2`. With 2 vCPU, concurrent organ calls share cores; first demo briefing latency is acceptable, throughput is not a goal.
- If the owner's plan has more RAM, models scale up through env (`STITCH_WHISPER_MODEL=small`, larger embedder) and limits are raised in an untracked `compose.local.yaml`.

### 3.5 Degraded modes (the "Compose profile" proposal)

Compose profiles are opt-in, so the all-five default cannot rely on a profile. Degraded modes are override files:

| Mode | Command | Effect |
|---|---|---|
| `full` (default) | `docker compose up` | all services, demo data, `fake` LLM, `prerendered` TTS, no egress |
| `lite` | `docker compose -f compose.yaml -f deploy/compose.lite.yaml up` | `eyes` and `voice` get `profiles: [off]` (not started); Brain gets `STITCH_ORGANS_DISABLED=eyes,voice` and reports them `disabled`; frontend shows both jars disabled. Saves about 1.2 GiB of limits. Eyes can run from precomputed demo output only if the Eyes spec supports it (not assumed). |
| `live` | `... -f deploy/compose.live.yaml up` | adds `egress` to brain, oracle, eyes, voice; `STITCH_MODE=live` selectable per request; secrets from `prod.env` |
| `prod` | `... -f deploy/compose.prod.yaml [--env-file prod.env]` | public ports, TLS, restart policy |

`lite` is also the automatic recommendation if the owner's plan is below 4 GB: README states it. Whisper size is separately configurable (`STITCH_WHISPER_MODEL=tiny`).

## 4. Images

### 4.1 Python organs and Brain (`organ.Dockerfile`, `brain.Dockerfile`)
```
# sketch only; exact digests resolved at implementation and bumped by Dependabot (docker ecosystem)
FROM ghcr.io/astral-sh/uv:<uv-version>-python3.12-bookworm-slim@sha256:<digest> AS build
  ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
  COPY pyproject.toml uv.lock packages/ organs/${ORGAN}/ ...        # workspace slice
  RUN --mount=type=cache,target=/root/.cache/uv  uv sync --frozen --no-dev --no-editable --package stitch-${ORGAN}
FROM python:3.12-slim-bookworm@sha256:<digest> AS runtime
  RUN useradd --uid 10001 --no-create-home app
  COPY --from=build /app/.venv /app/.venv      # plus demo data and models for this organ only
  USER 10001 ; ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
  CMD ["python","-m","stitch_${ORGAN}.server","--http","--host","0.0.0.0","--port","8000"]
```
- **Multi-stage, pinned by digest, non-root (uid 10001), no build tools, no dev dependencies.** `uv sync --frozen` fails if `uv.lock` is stale, so images match the lock.
- **Training dependencies never enter images.** Training libraries (PyTorch, Colab helpers) live in a `train` dependency group excluded by `--no-group train`; `check_images.py` asserts `torch` is not importable in any image and fails if a size budget is exceeded.
- **CPU-only.** Inference uses ONNX Runtime (CPU wheel) for Eyes, Oracle (if ONNX), and Library (embedder and reranker exported to ONNX), and CTranslate2 for Voice. No CUDA wheels. If a Library implementation insists on `sentence-transformers` (needs PyTorch), the dependency is pinned to the CPU index in `pyproject.toml` (`[[tool.uv.index]] name="pytorch-cpu" url="https://download.pytorch.org/whl/cpu" explicit=true`) and the Library budget is raised; this is a Library design decision and is called out in the issue list.
- **Runtime hardening** in Compose: `read_only: true`, `tmpfs: [/tmp:size=64m]`, `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, `user: "10001:10001"`. A service that needs a writable cache directory gets a named tmpfs for it, never a writable image layer.
- Models and demo data are copied into images (`/app/models`, `/app/data/demo`), so nothing downloads at runtime. Whisper weights are fetched at build time with a pinned revision and checksum (Voice design §3).
- `.dockerignore` excludes `.git`, `.kiro`, `data/raw`, `**/training`, `node_modules`, tests, `.venv`, notebooks.

### 4.2 Size budgets (targets, enforced by `check_images.py` against `deploy/image-budgets.json`)

| Image | Budget (compressed pull size is smaller; budget is on-disk) | Main contributors |
|---|---|---|
| stitch-brain | 300 MB | Python, FastAPI, MCP SDK, Pydantic |
| stitch-ledger | 500 MB | OR-Tools (large wheel) |
| stitch-oracle | 500 MB | numpy, scikit-learn or ONNX Runtime |
| stitch-eyes | 800 MB | ONNX Runtime, rasterio/GDAL wheels, model |
| stitch-library | 1000 MB | ONNX Runtime, tokenizers, embedder and reranker ONNX files, psycopg |
| stitch-voice | 800 MB | CTranslate2, PyAV (bundles FFmpeg), Whisper `base` int8 weights (a few hundred MB at most), prerendered audio |
| stitch-web | 120 MB | Caddy (alpine) plus static export plus map assets |
| postgres+pgvector | upstream | |
The figures are budgets set before measurement; task 5 records actual sizes and tightens the file. VPS disk: images for two releases (current and previous) must fit; about 8 GB total budget plus pgdata. If the plan has only 25 GB, `docker image prune` after each deploy keeps only the two newest tags (§9).

### 4.3 `web.Dockerfile`
Stage 1 `node:24-alpine@sha256` runs `npm ci`, `npm run build` (export to `out/`), `node scripts/csp-hashes.mjs` (§5.2). Stage 2 `caddy:2-alpine@sha256` copies `out/` to `/srv`, the Caddyfiles, and the generated CSP snippet. Runs as uid 10001 with `cap_add: NET_BIND_SERVICE` only in prod (80/443). Writable paths are the `/data` and `/config` volumes (`XDG_DATA_HOME`, `XDG_CONFIG_HOME`); ownership is set in the image so named volumes inherit it. (Verify in task 4 that the official Caddy binary keeps its bind capability when run as non-root.)

## 5. Gateway: Caddy

### 5.1 Caddyfile (production; the dev file is the same without the TLS global options)
```
{
	email {$ACME_EMAIL}
	# for dry runs: ACME_CA=https://acme-staging-v02.api.letsencrypt.org/directory (Let's Encrypt staging)
	acme_ca {$ACME_CA:https://acme-v02.api.letsencrypt.org/directory}
	admin off
	servers { protocols h1 h2 h3 }
}

{$SITE_ADDRESS} {
	import /etc/caddy/snippets/common.caddy
}

# container healthcheck and local checks only; plain HTTP on the loopback name, never redirected to HTTPS
http://127.0.0.1:8080 {
	handle /healthz { respond "ok" 200 }
}
```
The second site exists because port 80 on a domain site redirects to HTTPS, which would make an in-container `wget` healthcheck fail. In the base (dev and CI) Caddyfile, `SITE_ADDRESS=http://:8080` already answers `/healthz`.
`common.caddy`:
```
header {
	-Server
	X-Content-Type-Options nosniff
	Referrer-Policy strict-origin-when-cross-origin
	Permissions-Policy "camera=(), geolocation=(), microphone=(self), payment=()"
	Strict-Transport-Security "{$HSTS:max-age=300}"     # prod.env raises it after the dry run; no `preload`
	Content-Security-Policy "{$CSP}"                       # assembled at image build, see §5.2
	Cross-Origin-Opener-Policy same-origin
}

handle /healthz { respond "ok" 200 }

handle_path /api/* {                     # strips /api, forwards to the Brain
	request_body { max_size 4MB }        # 60 s of 16 kHz WAV is ~2.6 MB as base64
	reverse_proxy brain:8000 {
		flush_interval -1                # SSE: flush every write immediately
		transport http { dial_timeout 5s; response_header_timeout 30s }
		# Caddy sets X-Forwarded-For/-Proto; the Brain runs uvicorn with --proxy-headers and trusts only the web container
	}
}

handle {
	root * /srv
	encode zstd gzip                     # static assets only; not applied to /api (SSE must not be buffered or compressed)
	try_files {path} {path}/index.html
	file_server
	@hashed path /_next/static/*
	header @hashed Cache-Control "public, max-age=31536000, immutable"
	@map path /map/*
	header @map Cache-Control "public, max-age=604800"
	header /fonts/* Cache-Control "public, max-age=31536000, immutable"
}
```
Facts checked: Caddy flushes responses with `Content-Type: text/event-stream` immediately; `flush_interval -1` requests immediate flushing for every response (Caddy docs and community notes); both are set so SSE is safe even if a proxy in front changes content types. `handle_path` strips the matched prefix. HTTP-to-HTTPS redirect and certificate issuance and renewal are automatic when the site address is a public hostname (Caddy default behavior, DEP-R4.1). JSON API responses are not compressed (the sizes are small and avoiding `encode` on `/api` removes an SSE buffering risk). Final syntax is validated in CI with `caddy validate`.

**Dev and CI** use `SITE_ADDRESS=http://:8080`, which disables automatic HTTPS and ACME for that site; the same snippet is imported so the routes and headers are identical (HSTS is ignored over HTTP by browsers).

**`/api` route naming**: the frontend uses same-origin `/api/*`, the Brain's own routes have no prefix (`/briefings`, `/organs`, ...). `/api/organs` is the public status endpoint (DEP-R7.2); `/healthz` is the gateway liveness endpoint.

### 5.2 CSP compatible with Next (static export) and MapLibre
```
default-src 'self';
script-src 'self' 'sha256-<hash>' ... ;       # hashes of Next's inline bootstrap scripts, generated at build
style-src 'self' 'unsafe-inline';             # MapLibre and Motion set inline styles
img-src 'self' data: blob:;
font-src 'self';
connect-src 'self';                           # same-origin API, SSE, map GeoJSON
media-src 'self' blob:;                       # TTS audio via Blob URL
worker-src 'self' blob:; child-src blob:;     # MapLibre GL workers are created from blob URLs
object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'
```
- Next App Router static exports contain inline `<script>` blocks for hydration data. A static server cannot issue per-request nonces, so `scripts/csp-hashes.mjs` scans `out/**/*.html`, computes `sha256` of each inline script body, and writes the union into `csp.snippet` (an `env`-style file consumed as `{$CSP}`). Fallback if that proves brittle: `script-src 'self' 'unsafe-inline'`, recorded as a known weakness. Verify in task 4 by loading every route with the CSP and `console` open (no violations).
- `unsafe-inline` for styles is a deliberate trade for MapLibre and Motion; scripts stay strict.
- No external origins appear anywhere (fonts, tiles, and APIs are same-origin), so `connect-src 'self'` also enforces demo-first at the browser level. In live mode, the browser still talks only to the Brain; the Brain calls Open-Meteo.
- Microphone use needs `Permissions-Policy: microphone=(self)` (set above).
- HSTS starts at `max-age=300` for the dry run and is raised to one year in `prod.env` once HTTPS is verified; `preload` is not used.

## 6. Environment and secrets

### 6.1 `.env.example` (committed; names only, no secret values)
```
# --- selection ---
COMPOSE_PROJECT_NAME=stitch
TAG=local
GH_OWNER=
STITCH_MODE=demo
STITCH_LLM_PROVIDER=fake
STITCH_TTS_PROVIDER=prerendered          # demo default; azure|google need keys and the live override
STITCH_WHISPER_MODEL=base
STITCH_EMBED_MODEL=
STITCH_RERANK_MODEL=
STITCH_LAZY_LOAD=1
STITCH_ORGANS_DISABLED=
# --- production only (prod.env, never committed) ---
SITE_ADDRESS=stitch.aashirnoman.dev
ACME_EMAIL=
ACME_CA=
HSTS=max-age=31536000
# --- keys (leave empty; set only in prod.env on the VPS) ---
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
AZURE_SPEECH_KEY=
AZURE_SPEECH_REGION=
GOOGLE_APPLICATION_CREDENTIALS=
```
`STITCH_TTS_PROVIDER` default: `tech.md` lists `azure` as default falling back to `prerendered`. In Compose the default is `prerendered` so a clean machine has nothing to fall back from; with keys set, prod.env selects `azure`.

### 6.2 Where each secret lives
| Secret | Source | Reaches |
|---|---|---|
| Postgres owner, app and seed passwords | generated by `init-secrets` into the `secrets` volume on first start (`head -c 32 /dev/urandom | base64`, only if the file is absent) | postgres (`POSTGRES_PASSWORD_FILE`), seed, library, brain read them through `*_FILE` env variables |
| LLM, Azure, Google keys | `prod.env` on the VPS (mode 600, outside the repo) loaded with `--env-file`, or Docker file secrets for the Google JSON | brain and voice only; `stitch_common` settings support a `*_FILE` variant (e.g. `AZURE_SPEECH_KEY_FILE`) |
| SSH deploy key, host key, `VPS_HOST`, `VPS_USER` | GitHub Actions secrets (environment `production`) | cd.yml only |
| GHCR push | `GITHUB_TOKEN` with `packages: write` for the job | build-push |
- `deploy/secrets/`, `prod.env`, `.env` are git-ignored; `check_repo_hygiene.py` fails if any is tracked. `.gitignore` entries are checked to never match `.kiro`.
- No secret is passed as a build argument or baked into a layer (CI scans images with `gitleaks dir` on the build context and `docker history` is checked for env leaks).
- Logs never print env or keys (`stitch_common.logging` redaction, bootstrap).

### 6.3 Postgres init (`postgres/initdb/10-init.sh`, runs only on an empty data directory)
1. `CREATE EXTENSION IF NOT EXISTS vector;` in database `stitch`.
2. Roles with passwords read from `/secrets`: `stitch_owner` (owns schema, used by `seed` and migrations), `stitch_app` (runtime role for `library`: `SELECT` on index tables, `INSERT/UPDATE/DELETE` only on a small `ask_cache` table if the Library spec needs one).
3. `REVOKE ALL ON SCHEMA public FROM PUBLIC; REVOKE CONNECT ON DATABASE stitch FROM PUBLIC;` then explicit grants.
4. `POSTGRES_INITDB_ARGS=--auth-host=scram-sha-256` so password hashes and network auth use SCRAM.
5. Postgres listens on `core` only; no `ports:`.

## 7. First-start seeding (idempotent, DEP-R1.3, DEP-P5)

`seed` (library image, command `python -m stitch_library.seed`), run once per `up` (it exits quickly if nothing to do):
1. Connect as `stitch_owner`; `pg_advisory_lock(<fixed key>)` so two starts cannot race.
2. Apply migrations (additive only; expand-then-contract policy so the previous release still works after a new migration, which is what makes rollback safe).
3. Compare `seed_meta` (`corpus_sha256`, `embed_model`, `schema_version`) with the committed demo corpus manifest. Equal means log `already seeded` and exit 0.
4. Otherwise load chunks and embeddings in one transaction, using `INSERT ... ON CONFLICT (chunk_id) DO NOTHING`, with `chunk_id` = hash of (doc_id, page, span). Embeddings come from a committed precomputed file in `data/demo/library/` (fast, deterministic, no model download); if `STITCH_EMBED_MODEL` differs from the precomputed model, the seed recomputes with the configured model (slower, needs the baked model).
5. Update `seed_meta` in the same transaction.

Other organs read baked files; there is nothing to seed. Property DEP-P5 is checked by CI: `down` (without `-v`), `up`, compare `SELECT count(*), md5(string_agg(chunk_id, ''))`.

## 8. Logging, backup, restore

- **Logging**: `x-logging` anchor on every service: `driver: json-file`, `max-size: 10m`, `max-file: "3"` (DEP-R7.3). Apps emit structured JSON; Caddy logs JSON to stdout. VPS `daemon.json` sets the same defaults.
- **Backup** (DEP-R7.4): the Library index is reproducible from the seed, so Postgres backup is a convenience.
  ```
  docker compose exec -T postgres pg_dump -U stitch_owner -Fc stitch > /opt/stitch/backups/stitch-$(date +%F).dump
  ```
  Weekly cron under the deploy user keeps the last 4. Restore:
  ```
  docker compose exec -T postgres pg_restore -U stitch_owner -d stitch --clean --if-exists < dump
  ```
  Volume-level copy of `stitch_pgdata` (stop postgres first) is the alternative. `caddy_data` backup is a tarball (certificates are re-issuable, so also optional).

## 9. CI/CD

### 9.1 CI workflow (`ci.yml`, on push and pull_request)
```yaml
# design sketch of structure, not the final YAML
concurrency: { group: ci-${{ github.ref }}, cancel-in-progress: true }
permissions: { contents: read }
jobs:
  hygiene:                      # fast, no builds
    steps: checkout; python+uv (setup-uv with enable-cache); run deploy/bin/check_repo_hygiene.py;
           gitleaks; `docker compose config -q` for each override combination; `docker run caddy validate` on both Caddyfiles;
           check_ports.py (prod config); actionlint
  python:
    strategy: { matrix: { package: [stitch-common, brain, eyes, oracle, library, ledger, voice] }, fail-fast: false }
    services: { postgres: pgvector image }      # only library tests use it
    steps: setup-uv (cache keyed on uv.lock); uv sync --frozen --package ${{ matrix.package }};
           ruff; mypy --strict; pytest --hypothesis-profile=ci (sockets disabled by the plugin); check_contracts.py (stitch-common leg)
  evals-smoke:                  # needs python
    steps: uv sync --all-packages --frozen; python -m evals.run --fast --seed 0; upload evals/results as artifact
  frontend:
    steps: setup-node 24 (cache npm); npm ci; gen:types && git diff --exit-code; eslint; tsc --noEmit; vitest;
           next build (export); check-budget.mjs; playwright install chromium (cache ~/.cache/ms-playwright);
           playwright test --project=mock (includes axe); upload playwright-report on failure
  images:                       # needs python, frontend
    steps: docker/setup-buildx-action; docker buildx bake -f deploy/docker-bake.hcl --load (cache-from/to type=gha);
           check_images.py (size budgets, no torch, non-root); upload nothing
  stack-smoke:                  # needs images; DEP-R5.1, DEP-R10.2, DEP-P1, DEP-P5, DEP-P6
    steps: compose up -d --wait --wait-timeout 300 (time it; fail above the stated bound);
           negative control: in brain, an HTTPS request to example.com must FAIL;
           smoke.py http://127.0.0.1:8080; playwright test --project=stack (also fails on any non-same-origin request);
           compose down (no -v); compose up --wait; seed idempotence check; docker compose logs on failure
```
- **Offline check (DEP-P6)**: it is structural. `core` is `internal: true`, so containers have no route out; the job proves it with a negative control (an egress attempt must fail) instead of assuming. The browser leg asserts through `page.on('request')` that every request targets `127.0.0.1:8080`. No iptables rules are needed on the runner.
- DEP-R5.2: the `hygiene` job fails if any `.gitignore` matches `.kiro` or `git ls-files .kiro` is empty. DEP-R5.3: THIRD_PARTY check (§12). DEP-R5.4: caches for uv (setup-uv), npm (setup-node), Playwright browsers, and Docker layers (GHA cache).
- Runner capacity assumption: 2 vCPU, about 7 GB RAM, about 14 GB free disk (standard GitHub-hosted Linux runner; not re-verified here). The full stack's limits (3.4 GiB) fit; `lite` is the fallback for CI if memory proves short, with the Eyes and Voice UI checks run in the `mock` project instead.
- Third-party actions are pinned by commit SHA.

### 9.2 CD workflow (`cd.yml`)
```yaml
on: { workflow_run: { workflows: [CI], types: [completed], branches: [main] } }
permissions: { contents: read, packages: write }
jobs:
  publish:
    if: github.event.workflow_run.conclusion == 'success'
    steps: checkout @ workflow_run.head_sha; docker/login-action (registry ghcr.io, github.actor, GITHUB_TOKEN);
           buildx bake --push  -> ghcr.io/<owner>/stitch-<svc>:<sha> and :main (same GHA cache)
  deploy:
    needs: publish
    environment: production                     # optional required reviewer, holds the SSH secrets
    steps: write SSH key and pinned known_hosts (secret VPS_HOST_KEY, no trust-on-first-use);
           ssh -i key deploy@$VPS_HOST "<sha>"   # forced command, see below
           python deploy/bin/smoke.py https://stitch.aashirnoman.dev --timeout 120
           on smoke failure: ssh ... "rollback"; fail the job
```
- GHCR facts checked in docs/practice: pushing from Actions uses `GITHUB_TOKEN` with `packages: write`; a package is private by default, so after the first push the owner sets each package to **public** (one-time, six clicks; listed in the runbook) so the VPS needs no credentials. Alternative: a read-only PAT stored on the VPS (`docker login ghcr.io`). The first run of the workflow cannot pull until visibility is set; the Nov 20 dry run exists to find this.
- **SSH forced command.** `~deploy/.ssh/authorized_keys`:
  ```
  command="/usr/local/bin/stitch-deploy",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty ssh-ed25519 AAAA... github-actions-deploy
  ```
  `stitch-deploy` is root-owned (outside the repo checkout) and reads `$SSH_ORIGINAL_COMMAND`, accepting only `^[0-9a-f]{40}$` (a commit SHA) or `rollback`. The deploy user is in the `docker` group, which is effectively root on that host. The forced command, the single-purpose key, and a pinned host key limit what a leaked key can do; this residual risk is stated in the runbook.
- **`stitch-deploy <sha>`** (flock, so deploys are serialized):
  1. Save current `TAG` to `/opt/stitch/previous.env`.
  2. `git -C /opt/stitch/repo fetch --depth 50 origin main && git checkout --detach <sha>` (the repo is public; compose files and the Caddyfile come from the same commit as the images).
  3. `TAG=<sha> docker compose --env-file /opt/stitch/prod.env -f compose.yaml -f deploy/compose.prod.yaml pull`.
  4. `... run --rm seed` (migrations and idempotent seed; DEP-R6.1 "run migrations").
  5. `... up -d --remove-orphans --wait --wait-timeout 300`.
  6. Write `TAG` to `/opt/stitch/current.env`; `docker image prune -f` removes untagged images and tags other than current and previous.
- **Rollback** (DEP-R6.2): `ssh deploy@host rollback` reads `previous.env`, checks out that SHA, runs `up -d --wait` with the old `TAG`. Images of the previous tag are still on disk because of step 6's retention rule. One command, no rebuild. Migration policy (additive only) is what makes this safe.
- **Post-deploy smoke** runs from the GitHub runner against the public URL (tests DNS, certificate, Caddy routing, and the stack together).

## 10. VPS runbook (goes into `deploy/README.md`)

Assumed OS: Ubuntu 24.04 LTS (owner confirms; commands are Debian-family). Owner provides plan, region, SSH public key (§13).

1. **Create the instance** in the Vultr dashboard, add your SSH key, enable IPv4 (IPv6 optional; see DNS notes). Record vCPU and RAM in `deploy/README.md`. Attach a Vultr firewall group allowing only TCP 22, 80, 443 and UDP 443 (this is a second layer; see the Docker and UFW note below).
2. **Users and SSH**: `adduser stitch-admin`, add to `sudo`, copy the key; `adduser --disabled-password deploy`. In `/etc/ssh/sshd_config.d/10-hardening.conf`: `PermitRootLogin no`, `PasswordAuthentication no`, `KbdInteractiveAuthentication no`; `systemctl reload ssh`. Verify a second terminal can log in before closing the first.
3. **Firewall (UFW)**: `ufw default deny incoming; ufw default allow outgoing; ufw allow OpenSSH; ufw allow 80/tcp; ufw allow 443/tcp; ufw allow 443/udp; ufw enable`.
   **Important**: Docker publishes ports by writing its own iptables rules, which bypass UFW. UFW therefore does not protect published container ports. The design publishes only `web` (80, 443, and loopback 8080) and `check_ports.py` guards that; the Vultr firewall group is the real second layer.
4. **Automatic updates**: `apt install unattended-upgrades; dpkg-reconfigure -plow unattended-upgrades` (security updates only). `fail2ban` is optional for SSH (`apt install fail2ban`, default sshd jail); keys-only SSH already removes most of the risk.
5. **Swap**: 2 GiB swapfile (`fallocate -l 2G /swapfile; chmod 600; mkswap; swapon`; add to `/etc/fstab`), `vm.swappiness=10`.
6. **Docker Engine** from Docker's official apt repository (docker-ce, containerd.io, buildx and compose plugins), not Docker Desktop. `/etc/docker/daemon.json`: `{"log-driver":"json-file","log-opts":{"max-size":"10m","max-file":"3"},"live-restore":true}`. Add `deploy` to the `docker` group.
7. **Directories**: `/opt/stitch/{repo,backups}`; `git clone https://github.com/<owner>/<repo> /opt/stitch/repo` (public); `/opt/stitch/prod.env` from `deploy/env/prod.env.example` (mode 600, owner `deploy`); install `deploy/bin/deploy.sh` as `/usr/local/bin/stitch-deploy` (root:root 0755) and add the forced-command line to `authorized_keys`.
8. **DNS at name.com** (before step 9; propagation can take minutes):
   1. name.com → My Domains → `aashirnoman.dev` → DNS Records.
   2. Remove any existing record for host `stitch` that conflicts (A, AAAA, CNAME, URL forwarding, parking).
   3. Add record: Type **A**, Host **`stitch`**, Answer **`<VPS IPv4>`**, TTL **300**. (The fully qualified name is `stitch.aashirnoman.dev`; name.com's Host field takes only `stitch`.)
   4. AAAA: add one only if the VPS has IPv6 and the firewall allows 80/443 over IPv6; otherwise leave none. **A stale or wrong AAAA breaks certificate issuance** because validators may connect over IPv6.
   5. CAA: run `dig +short CAA aashirnoman.dev`. If any CAA record exists, it must permit the CA Caddy uses (`letsencrypt.org`, and `sectigo.com` or `pki.goog` if Caddy falls back to ZeroSSL/Google); otherwise issuance fails.
   6. Verify from your laptop (PowerShell): `nslookup stitch.aashirnoman.dev 1.1.1.1` and `nslookup stitch.aashirnoman.dev 8.8.8.8` must both return the VPS IP. On the VPS: `dig +short A stitch.aashirnoman.dev`, `dig +short AAAA stitch.aashirnoman.dev`.
9. **Certificate prerequisites** for Caddy's automatic HTTPS: the A record resolves publicly to this host; ports 80 and 443 are reachable from the internet (Vultr firewall, UFW, no other process on 80/443: `ss -ltnp | grep -E ':(80|443)\b'` must be empty before first start); the clock is correct (`timedatectl`); the volume `caddy_data` is persistent. First run uses Let's Encrypt **staging** (`ACME_CA` in `prod.env`) to avoid production rate limits while debugging; then remove `ACME_CA`, `docker compose down` the web service, delete the `caddy_data` volume contents (staging certs), and start again; raise `HSTS` only after the real certificate works.
10. **First start**: `cd /opt/stitch/repo && docker compose --env-file /opt/stitch/prod.env -f compose.yaml -f deploy/compose.prod.yaml up -d --wait`; `curl -I https://stitch.aashirnoman.dev/healthz`.
11. **Cron**: weekly pg_dump (§8). **Status**: `https://stitch.aashirnoman.dev/api/organs` and `/healthz`.

## 11. Smoke test (`deploy/bin/smoke.py`, DEP-R10, DEP-P6)
Stdlib only (`urllib`, `json`, `time`) so it runs on a runner, the VPS, or a laptop without installs. Steps, each with a timeout and a clear failure line:
1. `GET /healthz` is 200; `GET /en/` is 200 and contains the app title.
2. `GET /api/organs`: five organs `ready`; with `--allow-disabled eyes,voice` those two may be `disabled` (lite mode).
3. `POST /api/briefings {region: pk-sindh, scenario: sindh-2022, lang: en, mode: demo}`; read the SSE stream until `briefing` (max 90 s), asserting the event order includes `plan` then organ calls, no `error` event, `mode == demo`, five sections, `critic.passed`, every claim has at least one `EvidenceRef` (BRN-P1), at least one resolves via `GET /api/evidence/{run_id}`.
4. `POST /api/ask` with a seeded question returns an answer with citations or a labelled refusal.
5. Prints a JSON report (timings per step) and exits non-zero on the first failure.
Playwright adds the browser leg. The test is the same code path in CI, in CD, and on a developer machine (DEP-P1, P6).

## 12. Repository hygiene checks (`check_repo_hygiene.py`; pre-commit and CI)
| Check | Rule |
|---|---|
| `.kiro` not ignored (DEP-P3, R5.2, R8.2) | `git check-ignore .kiro` exits 1; no `.gitignore` line matches `.kiro`; `git ls-files .kiro` is non-empty and contains `steering`, `specs`, `hooks`, `agents`, `settings` |
| MCP settings clean (R8.3) | every string value in `.kiro/settings/mcp.json` that looks like a credential (regex list from the secret scanner) fails; `${VAR}` references pass |
| Secrets (DEP-P2, R3.3) | the bootstrap `secret_scan.py --all` plus gitleaks in CI; `.env`, `prod.env`, `deploy/secrets/**` must not be tracked |
| THIRD_PARTY (R5.3, best effort) | collect direct dependencies from every `pyproject.toml` and `package.json`; each normalized name must appear in `THIRD_PARTY.md` or in `deploy/third_party_allow.txt` (with reason). Transitive packages are not checked. The check is advisory on pull requests and blocking on `main`. Fonts and data sets are checked by an explicit list. |
| MANIFEST (R8.1) | every file under `data/demo/` except `.gitkeep` and `MANIFEST.md` appears in `data/demo/MANIFEST.md` with source and license columns |
| Files exist (R8.1, R9) | `LICENSE` (MIT text), `README.md`, `THIRD_PARTY.md`, `docs/kiro-writeup.md`, `deploy/README.md` |
| Ports (DEP-P4) | `check_ports.py` runs `docker compose config --format json` for the prod combination: only `web` has ports, host IP `127.0.0.1` for 8080 or `0.0.0.0` for 80, 443 only; every other service has none |
| Images | `check_images.py`: sizes within `image-budgets.json`, uid not 0, `torch` not importable |
| Steady commits (R8.4) | not machine-checkable; the README tracks it as a human practice |

## 13. Dry run on Nov 20 (de-risk DNS, HTTPS, GHCR, SSH)
Goal: `https://stitch.aashirnoman.dev` serves a placeholder, deployed by the real pipeline. Deliberately **excludes** organs, Postgres, and the frontend app, which do not exist yet.
1. (Owner, 1 h) Create the Vultr VPS, add the SSH key, record plan and region; follow runbook steps 1 to 7.
2. (Owner, 15 min) DNS A record (step 8) and verify with `nslookup`.
3. (Agent, 1.5 h) `web.placeholder.Dockerfile` (Caddy + `placeholder/index.html` and a `/api/organs` stub returning `{"status":"placeholder"}`), `docker-bake.hcl` target, `cd.yml` with a `DEPLOY_SERVICES=web` input, first GHCR push, set package visibility to public.
4. Start with Let's Encrypt **staging**; confirm a certificate is issued (browser warning is expected); then switch to production CA, confirm a valid certificate and HTTP-to-HTTPS redirect.
5. Run the CD deploy over SSH with the forced command; run `smoke.py --placeholder` (only `/healthz` and the page); test `rollback` once.
6. Record findings (open ports, certificate time, GHCR pull time, actual plan RAM) in `deploy/README.md`.
Exit: the placeholder is on the public URL, a push to `main` redeploys it, and rollback works. Everything after Nov 20 swaps the placeholder image for the real stack.

## 14. Facts the owner must supply
| Item | Why | Blocks |
|---|---|---|
| Vultr plan (vCPU, RAM, disk) and region | memory limits and image retention; lite vs full | task 6 sizing |
| VPS public IPv4 (and IPv6 if enabled) | DNS A and AAAA | Nov 20 |
| Deploy SSH key pair (public key to VPS; private key as GitHub secret `DEPLOY_SSH_KEY`), VPS host key fingerprint | forced-command deploy | Nov 20 |
| name.com account access to create the A record | DNS | Nov 20 |
| Email for ACME registration (`ACME_EMAIL`) | Let's Encrypt expiry notices | Nov 20 |
| GitHub repo name and owner (`GH_OWNER`) and permission to make GHCR packages public | image pull | Nov 20 |
| OS choice (default Ubuntu 24.04 LTS) | runbook commands | Nov 20 |
| API keys (Anthropic/OpenAI, Azure Speech key and region, Google credentials) if live mode or hosted TTS is wanted | optional features | none (demo works without) |
| Azure account that can create a Speech resource from Pakistan, region choice | Voice | Voice only |

## 15. Risks

| Risk | Mitigation |
|---|---|
| Full stack exceeds 4 GiB at peak | lazy loading, idle unload, limits (sum 3440 MiB), swap, `lite` mode, small default models, measured in task 6 |
| First CI stack run is slow or exceeds runner disk or RAM | GHA layer cache, `lite` fallback, images pruned between steps |
| DNS or certificate issuance fails | Nov 20 dry run with staging CA first; AAAA and CAA checks in the runbook |
| GHCR pull fails (private package) | set public after first push; documented, tested on Nov 20 |
| `required: false` dependency semantics differ from assumption | verify in task 6; fallback is retry logic in the Brain |
| Static export CSP needs script hashes | `csp-hashes.mjs`; fallback `unsafe-inline` with the risk recorded |
| Compose `include` not supported by the owner's Docker | version check in task 1; fallback root `compose.yaml` |
| Docker bypasses UFW | only `web` publishes ports; Vultr firewall; `check_ports.py` |
| Deploy user in `docker` group | forced command, restricted key, pinned host key; stated residual risk |
| Public images contain model weights with licenses | only MIT/permissive models in images; `local-mms` excluded from default images (VOX-R7.4); licenses listed in THIRD_PARTY.md |

## 16. Facts checked while writing
- Caddy SSE: Caddy flushes `text/event-stream` responses immediately and `flush_interval -1` forces immediate flushing for others (Caddy docs, community threads).
- pgvector image tag form `<pgvector-version>-pg<major>` (for example `0.8.7-pg16`) exists on Docker Hub; exact patch and digest to be pinned at implementation.
- faster-whisper does not need system FFmpeg because it decodes with PyAV (relevant to the Voice image).
- Not verified here: Compose `required: false` behavior on unhealthy services; the official Caddy image's non-root bind capability; exact image sizes; GitHub runner specs; Let's Encrypt staging URL (stated from memory: `acme-staging-v02.api.letsencrypt.org/directory`).

## Proposed contract changes
None to `mcp-contracts.md`. Cross-spec additions that deployment depends on:
1. **Brain**: `GET /healthz`; `STITCH_ORGANS_DISABLED` (comma list, organs reported `disabled`); organ endpoint URLs from env (`STITCH_ORGAN_URLS` or one variable per organ); `--proxy-headers` with trusted proxy limited to the `web` container so per-client rate limits see real client addresses; request body limit at least 4 MB on voice routes.
2. **`stitch_common` settings**: `*_FILE` variants for every secret variable.
3. **Library**: `python -m stitch_library.seed` CLI (idempotent, advisory lock, migrations) and a committed precomputed embeddings file with its model name in `data/demo/MANIFEST.md`.
4. **All organs**: `STITCH_LAZY_LOAD` and `STITCH_IDLE_UNLOAD_S` for model-holding organs; read-only filesystem compatibility (no writes outside `/tmp`).
5. **Voice**: provider name and hosted flag exposed through `/healthz` (the frontend design's `OrganHealth.meta`).
