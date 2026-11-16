# deployment: Requirements

Docker Compose, Caddy, CI/CD, repo hygiene. Prefix `DEP`.

## Introduction
Everything runs from `docker compose up` with the demo dataset, and is served at `https://stitch.aashirnoman.dev` on a Vultr VPS behind Caddy with automatic HTTPS.

## Requirements

### DEP-R1 One-command run
1. WHEN a user runs `docker compose up` on a clean machine with Docker, THE system SHALL start Postgres (pgvector), the five organs, the Brain, the frontend, and Caddy (production profile only), with no API keys and no network access needed after images are built or pulled.
2. THE default configuration SHALL use `STITCH_MODE=demo` and `STITCH_LLM_PROVIDER=fake`.
3. THE system SHALL load the demo dataset and seed the Library index automatically on first start, idempotently.
4. WHEN all services report healthy, THE Brain `/organs` SHALL list all five organs `ready`, or the unavailable organs SHALL be named with reason.
5. Compose SHALL use health checks and `depends_on: condition: service_healthy`.

### DEP-R2 Images
1. THE images SHALL be built from pinned base images, use multi-stage builds, run as non-root, and exclude dev dependencies and training data.
2. THE ML images SHALL be CPU-only and each stay under a stated size budget (set in design).
3. THE Compose file SHALL define resource limits per service sized for the target VPS.

### DEP-R3 Configuration and secrets
1. THE repo SHALL contain `.env.example` with variable names and no values for secrets.
2. THE system SHALL read LLM keys only from environment variables or a Docker secret.
3. A secret scan SHALL run pre-commit and in CI and fail on findings.
4. THE Postgres password and any admin tokens SHALL be generated or set per deployment, not hardcoded.

### DEP-R4 HTTPS and routing
1. THE Caddy service SHALL obtain and renew a certificate automatically for `stitch.aashirnoman.dev`, redirect HTTP to HTTPS, and route `/` to the frontend and `/api/*` to the Brain.
2. THE organs and Postgres SHALL NOT be reachable from the public internet (internal network only).
3. THE Caddy config SHALL set security headers (HSTS, CSP, X-Content-Type-Options, Referrer-Policy) and enable gzip/zstd.
4. SSE SHALL pass through Caddy without buffering.

### DEP-R5 CI
1. THE GitHub Actions workflow SHALL, on every push and pull request: lint (ruff, eslint), type-check (mypy, tsc), run unit and property tests (Hypothesis `ci` profile), validate contracts, run the eval smoke subset, run Playwright smoke tests against a Compose stack, and build images.
2. CI SHALL fail if `.kiro/` is listed in any `.gitignore` or not tracked by Git.
3. CI SHALL fail if THIRD_PARTY.md has no entry for a newly added dependency (best-effort check).
4. CI SHALL cache uv and npm dependencies.

### DEP-R6 CD
1. WHEN a commit is pushed to `main` and CI passes, THE pipeline SHALL deploy to the VPS over SSH (or by pull from a registry), run migrations, and run a post-deploy smoke test.
2. THE deploy SHALL keep the previous image tag to allow rollback with one command.
3. THE deploy credentials SHALL be GitHub Actions secrets, scoped to a restricted deploy user on the VPS.

### DEP-R7 Operations
1. THE VPS setup SHALL be documented in `deploy/README.md`: firewall (80, 443, SSH only), non-root user, unattended security updates, and DNS records.
2. THE system SHALL have health checks for each service and a status endpoint reachable through Caddy.
3. THE logs SHALL be structured and rotated (Docker log driver limits).
4. THE Postgres data SHALL live in a named volume with a documented backup command.

### DEP-R8 Repo and license hygiene
1. THE repo SHALL be public with an MIT `LICENSE`, `README.md`, `THIRD_PARTY.md`, and a `data/demo/MANIFEST.md` giving source and license of each committed data file.
2. THE repo SHALL commit `.kiro/` fully (specs, steering, hooks, agents, settings) and never ignore it.
3. THE MCP settings file SHALL contain no secrets (use env var references).
4. THE commit history SHALL show steady commits in the submission period.

### DEP-R9 Hackathon write-up support
1. THE repo SHALL include `docs/kiro-writeup.md` documenting each Kiro feature used (steering, specs, property tests, hooks, custom agent, MCP, powers, IDE vs CLI), updated as features land.

## Correctness properties (checked by scripts/CI, not Hypothesis)
- DEP-P1: a clean-clone `docker compose up` reaches all-healthy within a stated time on the target VPS size.
- DEP-P2: no file in the repo matches the secret-scan ruleset.
- DEP-P3: `git check-ignore .kiro` returns non-zero.
- DEP-P4: no organ port is bound to a public interface in the production profile.
- DEP-P5: bringing the stack down and up again preserves the seeded index and does not duplicate it.

## Out of scope
Kubernetes, multi-region, autoscaling, managed databases.

## Open questions
1. Deploy method: SSH + `docker compose pull` from GHCR (proposal) versus building on the VPS?
2. VPS size (vCPU/RAM)? It determines Whisper size, embedding model, and whether Eyes/Voice are enabled in production. Assumption: 4 vCPU / 8 GB.
3. DNS for `aashirnoman.dev` is already under your control and can point an A record to the VPS?
