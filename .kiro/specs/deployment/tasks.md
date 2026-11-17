# deployment: Tasks

Tags: `core` (must ship), `stretch`, `cuttable`, `owner` (needs the repo owner, not the agent). Each task lists the requirements and properties it satisfies, the tests or checks that prove it, a "Done when", and an estimate. Commit after each task (`feat(deploy): ...`, `ci: ...`).

Blocked by: **bootstrap** (CI skeleton, secret scan, `check_contracts.py`). Tasks in phase A need nothing else. Phase B tasks need the organs and the Brain to exist at least as stubs; each B task says what it needs.

## Phases and schedule

| Phase | Dates | Tasks | Exit |
|---|---|---|---|
| A. Dry run | Nov 20 (prep Nov 18 to 19) | 1 to 5 | `https://stitch.aashirnoman.dev` serves a placeholder deployed by the real pipeline, rollback tested |
| B. Real stack | Nov 22 to 30, as organs and frontend land | 6 to 12 | `docker compose up` brings up all services healthy on demo data; CI stack-smoke green |
| C. Hardening | Dec 1 | 13 to 17 | clean-clone start with network blocked passes; budgets measured; THIRD_PARTY audited |

Estimated total 46.5 h including 2 h of optional extras (about 5 h of it is owner time). The minimal path is 33 h (below).

## Minimal path (if time runs out)
Tasks 1, 2, 3, 4, 5 (dry run), 6, 7, 9, 10, 11 (CI reduced to: hygiene, python, frontend, stack-smoke), 12, 14. That yields a public HTTPS URL, a single-command stack on demo data, an offline smoke test in CI, and automated deploy with rollback.

**Cut order (first cut first):** (1) task 18 extras (Dependabot digest bumps, image scanning, fail2ban); (2) task 15 cron and restore rehearsal (keep the documented commands); (3) HTTP/3 and `Permissions-Policy` refinements; (4) task 16's advisory THIRD_PARTY check (keep the manual audit); (5) the `lite` override rehearsal (keep the file); (6) per-organ matrix in CI (run one combined job). Never cut: internal network, port check, secret scan, `.kiro` guard, offline smoke, rollback.

## Tasks

### Phase A: dry run (Nov 20)

- [x] **1. Repo hygiene and env scaffolding** `core` (2 h)
  - `deploy/bin/check_repo_hygiene.py` (all checks in design §12 that can run now: `.kiro` guard, MCP settings secret check, tracked-secret files, MANIFEST coverage, required files). Wire into the bootstrap CI and the git pre-commit hook.
  - `.gitignore` additions (`.env`, `prod.env`, `deploy/secrets/`, `data/raw/`), checked never to match `.kiro`. `deploy/env/.env.example` and `prod.env.example` (names only).
  - Tests: unit tests for the script with temporary git repos (a bad `.gitignore` containing `.kiro`, a tracked `.env`, a credential-looking value in `mcp.json`, an unlisted demo file). Refs: DEP-R3.1, R3.3, R5.2, R8.1 to R8.3, P2, P3.
  - Done when: each seeded violation fails the script with a clear message and a clean repo passes.

- [ ] **2. Provision the VPS and DNS** `owner` (2.5 h)
  - Follow design §10 steps 1 to 8: Vultr instance, users, SSH hardening, UFW and Vultr firewall, unattended upgrades, swap, Docker Engine, directories. Create the name.com A record for `stitch` (TTL 300). Record vCPU, RAM, disk, region, IPv4 in `deploy/README.md`. Generate the deploy key pair; add the forced-command line; store `DEPLOY_SSH_KEY`, `VPS_HOST`, `VPS_USER`, `VPS_HOST_KEY` as GitHub environment secrets.
  - Checks: `nslookup stitch.aashirnoman.dev 1.1.1.1` returns the IPv4; `dig AAAA` and `dig CAA` reviewed; `ss -ltnp` shows nothing on 80 and 443; `ssh deploy@host true` is refused (forced command accepts only a SHA or `rollback`). Refs: DEP-R7.1, R6.3.
  - Done when: the checks pass and plan numbers are recorded (this unblocks sizing).

- [x] **3. Placeholder web image, Caddyfiles, production override** `core` (2 h)
  - `deploy/docker/web.placeholder.Dockerfile`, `placeholder/index.html` (states "Stitch is being assembled", links to the repo), `Caddyfile`, `Caddyfile.prod`, `snippets/common.caddy` (headers, compression, `/healthz`, `/api/*` proxy with `flush_interval -1` and a `respond 503` fallback for the absent Brain), `compose.prod.yaml`, minimal `deploy/compose.yaml` with `web` only, `docker-bake.hcl` with the `web` target.
  - Checks: `docker run caddy validate` for both Caddyfiles in CI; local `docker compose up web` serves the placeholder on `127.0.0.1:8080`; `curl -I` shows the security headers and `Content-Encoding: zstd` or gzip for the page. Refs: DEP-R4.1, R4.3, R4.4.
  - Done when: the placeholder runs locally and the Caddyfiles validate.

- [ ] **4. Minimal CD: publish, SSH deploy, rollback** `core` (3 h)
  - `cd.yml` (workflow_run after CI on `main`; build and push `web` to GHCR tagged by SHA and `main`; deploy job with environment `production`; pinned known_hosts; forced-command call; post-deploy smoke; rollback on failure). `deploy/bin/deploy.sh` installed as `/usr/local/bin/stitch-deploy` (flock, SHA validation, previous tag recorded, `pull`, `up -d --wait`, image retention of current and previous). `deploy/bin/smoke.py --placeholder` (healthz and page only).
  - Set the GHCR package visibility to public after the first push (record the click path in the runbook).
  - Checks: shell tests for the SHA validation (accepts 40 hex, rejects `; rm -rf`, `../`, empty); a deliberate failing smoke triggers rollback. Refs: DEP-R6.1 to R6.3.
  - Done when: a push to `main` deploys the placeholder and a forced bad deploy rolls back.

- [ ] **5. Run the dry run** `owner` + agent (1.5 h)
  - Design §13: start with Let's Encrypt staging, confirm issuance, switch to the production CA, clear `caddy_data` staging certificates, confirm a valid certificate, HTTP to HTTPS redirect, and `https://stitch.aashirnoman.dev/healthz`. Run CD once end to end; run `rollback` once.
  - Record in `deploy/README.md`: time to certificate, pull time, open ports (`nmap` or `nc -z` from a laptop to 22, 80, 443 and closed 5432, 8000), actual plan.
  - Done when: the placeholder is live on the public URL with a trusted certificate, CD redeploys it, rollback works. Refs: DEP-R4.1, R6, R7.1.

### Phase B: real stack

- [ ] **6. Compose base: topology, secrets, Postgres, healthchecks, limits** `core` (4 h) *(needs organ and Brain stubs that answer `/healthz`)*
  - `deploy/compose.yaml` per design §3 (all services, `core` internal and `edge` networks, volumes, `init-secrets`, Postgres init script with extension and roles, `seed` placeholder, healthchecks, `depends_on` conditions, `x-logging`, `read_only`, `tmpfs`, `cap_drop`, `no-new-privileges`, memory and CPU limits). Root `compose.yaml` with `include`. Overrides `compose.live.yaml`, `compose.lite.yaml`, `compose.ci.yaml`.
  - Verify and record: Compose `include` works on the target Docker versions (local and CI and VPS); `required: false` semantics for Eyes and Voice (design §3.1); a fresh volume start generates secrets once and a second start does not regenerate them.
  - Checks: `docker compose config -q` for every override combination (CI); containers on `core` cannot reach the internet (negative control); Postgres refuses connections without the password; `psql` as `stitch_app` cannot `CREATE TABLE`. Refs: DEP-R1.1, R1.4, R1.5, R2.3, R3.4, R4.2, R7.2, R7.3, P4.
  - Done when: `docker compose up --wait` reaches all-healthy with stub organs and secrets are not in `docker inspect` env output.

- [ ] **7. Python images: organ and Brain Dockerfiles** `core` (4 h) *(needs each organ's package to install)*
  - `organ.Dockerfile` and `brain.Dockerfile` per design §4.1: pinned digests, `uv sync --frozen --no-dev --package`, non-root uid 10001, CPU-only wheels, demo data and models copied in, no training group. `.dockerignore`. `docker-bake.hcl` targets for all services with GHA cache.
  - `deploy/bin/check_images.py` and `deploy/image-budgets.json` (initial budgets from design §4.2; update after measuring).
  - Checks: images build from a clean clone; `torch` is not importable; uid is not 0; size budget check; the container starts with a read-only root filesystem. Refs: DEP-R2.1, R2.2, R2.4.
  - Done when: all six Python images build, pass `check_images.py`, and start under the hardened runtime options.

- [ ] **8. Idempotent seed job** `core` (2 h) *(needs the Library's schema and the committed precomputed embeddings)*
  - Wire `seed` into Compose with the advisory lock, migration step, `seed_meta` comparison (design §7). The Library spec owns `python -m stitch_library.seed`; this task integrates and tests it in the stack.
  - Checks (CI stack job): first start seeds; `down` then `up` (no `-v`) logs `already seeded` and chunk count plus hash are unchanged; two concurrent seed runs leave one copy; a changed `STITCH_EMBED_MODEL` triggers a recompute. Refs: DEP-R1.3, P5.
  - Done when: the DEP-P5 check passes.

- [ ] **9. Full web image: frontend export, CSP, gateway** `core` (3 h) *(needs the frontend export build; can use the shell app early)*
  - `web.Dockerfile` (node build stage and Caddy runtime), `scripts/csp-hashes.mjs` in the frontend, `{$CSP}` assembly, `/api/*` proxy to `brain:8000`, `request_body max_size 4MB`, static caching headers, non-root run with `NET_BIND_SERVICE` in prod.
  - Checks: Playwright (frontend `stack` project) loads `/en/` and `/ur/` with zero CSP violations in the console; map renders with the CSP (workers from blob); SSE events arrive progressively through the gateway (first `organ_call` event reaches the client before the run finishes, measured with timestamps); a response header test for each header in design §5.1. Refs: DEP-R4.1, R4.3, R4.4.
  - Done when: the real frontend is served by the gateway on `127.0.0.1:8080` with a clean console and live SSE.

- [x] **10. Stack smoke script** `core` (2 h)
  - `deploy/bin/smoke.py` (stdlib only), steps from design §11, `--allow-disabled`, `--placeholder`, timings report, non-zero on failure.
  - Tests: unit tests of the SSE parser and assertions against the frontend mock Brain (reusing its fixtures), including failure cases (missing evidence, error event, wrong order). Refs: DEP-R10.1, P6.
  - Done when: the script passes against the mock Brain and fails on each seeded defect.

- [ ] **11. Full CI workflow** `core` (5 h)
  - `ci.yml` per design §9.1: `hygiene`, `python` matrix (uv cache, Postgres service for Library), `evals-smoke`, `frontend` (types drift, lint, tsc, Vitest, build, budget, Playwright `mock` with axe), `images` (bake with GHA cache, `check_images.py`), `stack-smoke` (compose up with timing, negative control, `smoke.py`, Playwright `stack`, restart and seed idempotence). Pin third-party actions by SHA. Upload reports on failure.
  - Checks: a PR with a seeded failure per job (stale generated types, torch in an image, an extra published port, an ignored `.kiro`) fails exactly the intended job. Refs: DEP-R5.1 to R5.4, R10.2.
  - Done when: CI is green on `main` and each seeded failure is caught. Record the duration; if over 20 minutes, split or cache further.

- [ ] **12. Offline guarantee and port audit** `core` (2 h)
  - `check_ports.py` on the prod and default compose configurations; browser request audit in the Playwright `stack` project (fail on any request to a host other than the gateway); negative-control step (HTTPS request from `brain` and `voice` must fail in default mode and succeed with `compose.live.yaml` where an egress network exists, tested against a local HTTP server, not the internet).
  - Checks: adding `ports: ["5432:5432"]` to Postgres fails `check_ports.py`; removing `internal: true` fails the negative control. Refs: DEP-R4.2, R10.1, R10.2, P4, P6.
  - Done when: both seeded regressions are caught in CI.

### Phase C: hardening (Dec 1) and finishing

- [ ] **13. Measure memory and tune the budget** `core` (3 h)
  - Run the demo briefing, then Voice transcribe and speak, then an Ask, while sampling `docker stats` (1 s) on the owner's VPS (or a 2 vCPU / 4 GiB VM). Update the design §3.4 table with measured idle and peak, set limits (never raise a limit above the 3496 MiB total; choose a smaller default model instead). Verify lazy load and idle unload work (Eyes, Voice, Library reranker). Rehearse `lite`. Record DEP-P1 time to all-healthy.
  - Done when: the table has measured numbers, limits sum within the floor, no OOM kill in a 10-run loop, and the measured time-to-healthy is written into the README. Refs: DEP-R2.3, R2.4, P1.

- [ ] **14. Full CD** `core` (2 h)
  - Extend `cd.yml` to publish and deploy every image, run migrations (`run --rm seed`), `up -d --wait`, public smoke, automatic rollback on smoke failure. Test: deploy a commit, then deploy a commit that breaks `/api/organs` (rollback must trigger), then `rollback` manually.
  - Done when: a push to `main` updates the live site end to end and both rollback paths work. Refs: DEP-R6.1, R6.2, R10.3.

- [ ] **15. Operations runbook, backup, restore** `core` for the runbook, `cuttable` for the rehearsal (2 h)
  - `deploy/README.md`: runbook (design §10), owner facts, deploy and rollback commands, certificate troubleshooting, memory table, backup and restore commands, `lite` and `live` usage, how to read logs. Rehearse one `pg_dump` and `pg_restore` into a scratch database.
  - Done when: someone who has never seen the project can redeploy from the README, and the restore rehearsal is recorded. Refs: DEP-R7.1 to R7.4.

- [ ] **16. THIRD_PARTY and MANIFEST audit** `core` (2 h)
  - Add the THIRD_PARTY dependency check (best effort, advisory on PRs, blocking on `main`) and the explicit list for fonts, models, datasets, and the Docker base images (Caddy, Postgres, pgvector, Python, uv, Alpine). Hand-audit every direct dependency across `uv.lock` and `package.json`. Confirm every `data/demo` file has a MANIFEST row.
  - Done when: the check passes and the manual audit is signed off in the PR. Refs: DEP-R5.3, R8.1, P2.

- [ ] **17. Clean-clone acceptance** `core` (1.5 h)
  - On a machine with only Docker: `git clone`, `docker compose up --wait`, open `http://127.0.0.1:8080`, run the default briefing; repeat with the network disabled after the images exist; run `smoke.py`. Confirm `git check-ignore .kiro` fails and `git ls-files .kiro` is non-empty on the clone.
  - Done when: both runs pass, time to healthy is recorded, and the write-up lists them as the acceptance evidence. Refs: DEP-R1.1, R1.2, R10.1, P1, P3, P6.

- [ ] **18. Extras** `stretch` (2 h)
  - Dependabot config (docker, github-actions, npm, pip) to bump digests and action SHAs; Trivy or Grype scan of images in CI (report only); fail2ban on the VPS; `compose.lite` in CI as a second stack job.

- [ ] **19. Kiro write-up entries** `core` (1 h)
  - Add to `docs/kiro-writeup.md`: how the specs drove the deployment, hooks that guard `.kiro`, which Powers (if any) were used for Docker or databases, and what the agent verified versus what the owner supplied (DEP-R9).
  - Done when: the section exists and matches what was built.

## Estimates

| Task | Hours | Who | Task | Hours | Who |
|---|---|---|---|---|---|
| 1 | 2 | agent | 11 | 5 | agent |
| 2 | 2.5 | owner | 12 | 2 | agent |
| 3 | 2 | agent | 13 | 3 | agent + owner (VPS) |
| 4 | 3 | agent | 14 | 2 | agent |
| 5 | 1.5 | owner + agent | 15 | 2 | agent |
| 6 | 4 | agent | 16 | 2 | agent |
| 7 | 4 | agent | 17 | 1.5 | agent |
| 8 | 2 | agent | 18 | 2 | agent |
| 9 | 3 | agent | 19 | 1 | agent |
| 10 | 2 | agent | | | |

Total 46.5 h including the optional extras (task 18). Owner time is about 5 h (tasks 2, 5, and the VPS part of 13). The minimal path (1 to 7, 9 to 12, 14) is 33 h. Phase A (tasks 1 to 5, 11 h) is a full day plus the owner's tasks prepared on Nov 18 to 19, so Nov 20 is tight if other work overlaps; if it slips, tasks 1 and 3 can move to Nov 18 to 19 since they need nothing else.

## Traceability

| Requirement | Tasks |
|---|---|
| DEP-R1 | 6, 8, 17 |
| DEP-R2 | 6, 7, 13 |
| DEP-R3 | 1, 6 |
| DEP-R4 | 3, 6, 9, 12 |
| DEP-R5 | 1, 11, 16 |
| DEP-R6 | 2, 4, 14 |
| DEP-R7 | 2, 5, 6, 15 |
| DEP-R8 | 1, 16 |
| DEP-R9 | 19 |
| DEP-R10 | 10, 11, 12, 14, 17 |

| Property | Task | Check |
|---|---|---|
| DEP-P1 | 13, 17 | measured time to healthy on the target VPS size, recorded; CI timing guard |
| DEP-P2 | 1, 11, 16 | secret scan and gitleaks |
| DEP-P3 | 1, 11, 17 | `git check-ignore .kiro` returns non-zero |
| DEP-P4 | 6, 12 | `check_ports.py` on the production config |
| DEP-P5 | 8, 11 | down/up chunk count and hash unchanged |
| DEP-P6 | 10, 11, 12, 17 | internal network, negative control, smoke script, Playwright request audit |
