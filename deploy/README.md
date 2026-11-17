# Stitch deployment runbook

Everything here implements `.kiro/specs/deployment/` (DEP-R1 to R10). One Compose project runs the whole system from committed demo data. A Caddy gateway (`web`) serves the static frontend, proxies `/api/*` to the Brain and terminates TLS. Organs, the Brain and Postgres sit on the internal `core` network, which has no route to the internet, so the demo needs no network after the images exist.

Stitch is a decision-support demo, not an operational warning system.

## Quick start (any machine with Docker)

```bash
docker compose up -d --wait                       # Postgres, Library, Ledger, Oracle, Brain, gateway
open http://localhost/                            # gateway on 127.0.0.1:80 (WEB_PORT, WEB_BIND)
COMPOSE_PROFILES=eyes STITCH_ORGANS_DISABLED=voice docker compose up -d --wait   # plus Eyes
python3 deploy/bin/smoke.py http://127.0.0.1 --allow-disabled eyes,voice          # smoke test
```

No `.env` and no keys are needed: `STITCH_MODE=demo`, `STITCH_LLM_PROVIDER=fake`, `STITCH_TTS_PROVIDER=prerendered`. Postgres passwords are generated on first start into the `secrets` volume by `init-secrets` and never printed.

| Mode | Command | Effect |
|---|---|---|
| default | `docker compose up -d --wait` | core organs; Eyes and Voice not started and reported `disabled` |
| with Eyes | `COMPOSE_PROFILES=eyes STITCH_ORGANS_DISABLED=voice docker compose up -d --wait` | adds the Eyes organ |
| full | `COMPOSE_PROFILES=full STITCH_ORGANS_DISABLED= docker compose up -d --wait` | Eyes and Voice (Voice once `organs/voice` exists) |
| lite (< 4 GB) | `docker compose -f compose.yaml -f deploy/compose.lite.yaml up -d --wait` | no reranker, smaller Postgres and Library limits |
| live | `... -f deploy/compose.live.yaml up -d --wait` | adds the `egress` network to Brain, Oracle, Library, Eyes, Voice; keys from `prod.env` |
| prod | `docker compose --env-file /opt/stitch/prod.env -f compose.yaml -f deploy/compose.prod.yaml up -d --wait` | ports 80/443, Caddyfile.prod (TLS when SITE_ADDRESS is a domain), ACME volumes |

The repository root `compose.yaml` holds the base file directly (the design's `include` fallback), so a clean clone works with `docker compose up` from the root.

## Files

| Path | What |
|---|---|
| `compose.yaml` | services, `core` (internal) and `edge` networks, volumes, healthchecks, `depends_on: service_healthy`, limits, log rotation, hardening |
| `deploy/compose.{prod,lite,live,ci}.yaml` | overrides (above) |
| `deploy/docker/python.Dockerfile` | one multi-stage image for every Python service (pinned digests, `uv sync --frozen --no-dev`, uid 10001, CPU-only, models baked) |
| `deploy/docker/web.Dockerfile` | Next.js static export (node:24-alpine) served by Caddy (caddy:2-alpine), CSP hashes at build |
| `deploy/docker/postgres/initdb/10-init.sh` | `vector` extension, `stitch_owner` and `stitch_app` roles, grants |
| `deploy/docker/init-secrets.sh`, `library_seed.py` | first-start secrets; idempotent Library seed under an advisory lock |
| `deploy/caddy/` | `Caddyfile` (dev, CI), `Caddyfile.prod`, `snippets/common.caddy` (headers, compression, SSE, `/api` proxy) |
| `deploy/docker-bake.hcl` | build graph (`default`, `all`, `placeholder`) |
| `deploy/bin/smoke.py` | stdlib-only smoke test (gateway, organs, SSE briefing, evidence, ask) |
| `deploy/bin/offline_smoke.sh` | DEP-P6: negative egress control, positive control, smoke, seed idempotence |
| `deploy/bin/check_{ports,images,repo_hygiene}.py` | DEP-P4 port audit, image budgets, repo hygiene |
| `deploy/bin/deploy.sh` | forced command `stitch-deploy` on the VPS (deploy, rollback, status) |
| `deploy/bin/check_dns.sh` | `stitch-check-dns`: switches to the domain and HTTPS once DNS resolves |
| `deploy/bin/backup.sh` | `stitch-backup`: pg_dump, restore, restore rehearsal |
| `deploy/bin/vps_setup.sh` | idempotent host setup (deploy user, sudo rule, scripts, UFW, cron, sshd, unattended upgrades) |
| `deploy/playwright/` | browser leg against the running stack (CSP, same-origin requests, demo briefing) |

## The VPS (owner facts)

| Item | Value |
|---|---|
| Provider, region | Vultr, Atlanta (ATL) |
| Plan | 2 vCPU, 16 GB RAM (+ 8 GB swap), 112 GB disk |
| OS | Ubuntu 24.04.5 LTS, Docker Engine 29.10, Compose v5.7.1 |
| IPv4 | 64.177.59.11 (no global IPv6 address, so no AAAA record) |
| SSH host key | `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAII4c2fujhEUGknrPXPMdLpbPK6tiJWRBi2cXBtxLOcqR` |
| Also runs | the Eyes CPU training job under `/srv/data` (niced). Image builds use `nice -n 10` and run one at a time. |

Layout on the host:

| Path | Purpose |
|---|---|
| `/srv/stitch.git`, `/srv/stitch` | bare repository the owner pushes to (`git push vultr main`) and the owner's working clone |
| `/opt/stitch/repo` | the deploy checkout (detached at the running sha); compose files come from the same commit as the images |
| `/opt/stitch/prod.env` | production settings, mode 600 (from `deploy/env/prod.env.example`) |
| `/opt/stitch/deploy.conf` | `ORIGIN_URL`, `PUBLIC_IP`, `SMOKE_URL`, `BUILD_MISSING`, `COMPOSE_OVERRIDES` (extra `deploy/compose.<x>.yaml` files after the prod override) |
| `/opt/stitch/{current,previous}.env` | release shas for rollback |
| `/opt/stitch/deploy.log`, `dns.log`, `backup.log`, `backups/` | logs and dumps |
| `/usr/local/bin/stitch-{deploy,check-dns,backup}` | installed from `deploy/bin/` (root-owned 0755) |

### Setup (runbook, design section 10)

All of this is automated and idempotent in `deploy/bin/vps_setup.sh`:

```bash
# as root, from a checkout
PUBLIC_IP=64.177.59.11 DEPLOY_PUBKEY="$(cat stitch_deploy.pub)" bash deploy/bin/vps_setup.sh
```

1. **Users and SSH.** `deploy` has no password and no shell: its only key is bound to the forced command. sshd is keys-only (`/etc/ssh/sshd_config.d/05-stitch-hardening.conf`: `PasswordAuthentication no`, `PermitRootLogin prohibit-password`); root keeps key login for the owner. Check a second login works before closing the first session.
2. **Firewall.** UFW default deny incoming, allow 22/tcp, 80/tcp, 443/tcp, 443/udp. Docker writes its own iptables rules for published ports and bypasses UFW, so only `web` publishes ports (`check_ports.py` enforces it). If you add a Vultr firewall group, allow the same four.
3. **Automatic security updates.** `unattended-upgrades` with `/etc/apt/apt.conf.d/20auto-upgrades`.
4. **Swap.** 8 GB already present (the design asks for at least 2 GB).
5. **Docker logs.** Every service has `json-file` with `max-size 10m`, `max-file 3` in `compose.yaml`. `/etc/docker/daemon.json` is not changed on this host, because applying it restarts dockerd under the running training job.
6. **Deploy user and forced command.** `~deploy/.ssh/authorized_keys`:
   ```
   command="/usr/local/bin/stitch-deploy",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty ssh-ed25519 AAAA... github-actions-deploy
   ```
   `/etc/sudoers.d/stitch-deploy`: `deploy ALL=(root) NOPASSWD: /usr/local/bin/stitch-deploy`. `deploy` is **not** in the `docker` group (membership would be root-equivalent). The script accepts only a 40-hex sha, `rollback` or `status` and validates the argument before it calls sudo and again as root. Residual risk: a leaked key can deploy any commit that exists in the origin repository or roll back.
7. **Cron** (`/etc/cron.d/stitch`): `stitch-check-dns` every 5 minutes, `stitch-backup` Sundays 03:30 UTC.

## DNS at name.com (owner action)

`stitch.aashirnoman.dev` does not resolve yet. Until it does, the site is served over plain HTTP on the IP: `prod.env` has `SITE_ADDRESS=:80`.

1. Sign in at name.com, open **My Domains**, choose `aashirnoman.dev`, then **Manage DNS Records**.
2. Delete any record for host `stitch` (A, AAAA, CNAME, URL forwarding, parking).
3. Add a record: **Type** `A`, **Host** `stitch`, **Answer** `64.177.59.11`, **TTL** `300`. Save. (The Host field takes only `stitch`; name.com appends the domain.)
4. Do not add an AAAA record: the VPS has no public IPv6, and a wrong AAAA breaks certificate issuance.
5. CAA: `dig +short CAA aashirnoman.dev` currently returns nothing, which allows every CA. If you add CAA records later, include `0 issue "letsencrypt.org"`.
6. Verify from your laptop (PowerShell):
   ```powershell
   nslookup stitch.aashirnoman.dev 1.1.1.1
   nslookup stitch.aashirnoman.dev 8.8.8.8      # both must answer 64.177.59.11
   ```

**What happens next, automatically.** Within 5 minutes `stitch-check-dns` sees the A record on both 1.1.1.1 and 8.8.8.8, sets `SITE_ADDRESS=stitch.aashirnoman.dev` in `prod.env`, recreates only the `web` container, and waits up to 3 minutes for `https://stitch.aashirnoman.dev/healthz`. Caddy obtains a Let's Encrypt certificate (HTTP-01 or TLS-ALPN-01 on ports 80/443) and from then on redirects HTTP to HTTPS and renews on its own. On success the script points the deploy smoke at the HTTPS URL. If issuance fails it goes back to `:80`, so the site stays reachable, and waits an hour before trying again (Let's Encrypt limits failed validations). Watch it with `tail -f /opt/stitch/dns.log`, or run it by hand:

```bash
stitch-check-dns --dry-run      # report only
stitch-check-dns                # switch now
curl -I https://stitch.aashirnoman.dev/healthz
```

After HTTPS works, raise HSTS in `/opt/stitch/prod.env` to `HSTS=max-age=31536000` (no `preload`) and recreate web (`stitch-deploy <current sha>` or the `up -d --no-deps web` line below). To debug issuance against the Let's Encrypt staging CA first, set `ACME_CA=https://acme-staging-v02.api.letsencrypt.org/directory`; afterwards remove it and delete the staging certificates (`docker volume rm stitch_caddy_data` with web stopped).

Certificate troubleshooting: `docker logs stitch-web-1 2>&1 | grep -iE 'acme|certificate|challenge'`; `ss -ltnp | grep -E ':(80|443)\b'` must show only docker-proxy; `timedatectl` must say synchronized; the `caddy_data` volume must persist (it holds the certificates and the ACME account).

## Deploy, rollback, status

```bash
# from the laptop, after committing locally
git push vultr main
ssh root@64.177.59.11 stitch-deploy "$(git rev-parse HEAD)"     # or as the deploy user:
ssh -i ~/.ssh/stitch_deploy_ed25519 deploy@64.177.59.11 "$(git rev-parse HEAD)"
ssh -i ~/.ssh/stitch_deploy_ed25519 deploy@64.177.59.11 rollback
ssh -i ~/.ssh/stitch_deploy_ed25519 deploy@64.177.59.11 status
```

`stitch-deploy <sha>` (serialized with flock): fetch from `ORIGIN_URL`, check out the sha in `/opt/stitch/repo`, get images tagged with the sha (pull from GHCR; with `BUILD_MISSING=1` build any missing image locally, niced, one at a time), `run --rm seed` (migrations and idempotent seed), `up -d --remove-orphans --wait`, run `smoke.py` against `SMOKE_URL`, then record `current.env` and `previous.env` and prune images other than the current and previous release. If health or smoke fails it rolls back to the release that was running. `rollback` checks out the previous sha and starts its images (still on disk), with no rebuild. Migrations are additive only, which is what keeps rollback safe.

Manual commands on the host (same project the deploy uses):

```bash
cd /opt/stitch/repo
alias dc='TAG=$(sed -n s/^TAG=//p /opt/stitch/current.env) docker compose --env-file /opt/stitch/prod.env -f compose.yaml -f deploy/compose.prod.yaml -f deploy/compose.live.yaml'
# compose.live.yaml is in the list because deploy.conf has COMPOSE_OVERRIDES="deploy/compose.live.yaml"
# (egress for Oracle live mode and Deepgram voice). STITCH_LLM_PROVIDER stays fake, see docs/decisions.md.
dc ps                                  # states and health
dc logs -f --tail 100 brain            # JSON logs per service (rotated: 3 x 10 MB)
dc up -d --no-deps web                 # recreate the gateway after a prod.env change
docker stats --no-stream               # memory and CPU
```

### CD from GitHub (once the repository is on GitHub)

`.github/workflows/cd.yml` runs after CI succeeds on `main`: bake and push every image to `ghcr.io/<owner>/stitch-<service>:<sha>` (and `:main`), SSH to `deploy@VPS_HOST` with the sha (forced command), run `smoke.py` against `vars.PUBLIC_URL` from the runner, and call `rollback` if the smoke fails. `workflow_dispatch` offers `deploy` and `rollback`.

Owner steps:
1. Create the public GitHub repository, add it as a remote, push `main`.
2. Repository **Settings → Environments → New environment** `production`. Add secrets: `DEPLOY_SSH_KEY` (contents of `C:\Users\HP\.ssh\stitch_deploy_ed25519`, the private half of the key already installed for `deploy`), `VPS_HOST` = `64.177.59.11`, `VPS_HOST_KEY` = `64.177.59.11 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAII4c2fujhEUGknrPXPMdLpbPK6tiJWRBi2cXBtxLOcqR`. Add variable `PUBLIC_URL` = `http://64.177.59.11` (change to `https://stitch.aashirnoman.dev` once DNS works). Optionally require a reviewer.
3. After the first CD run, make each package public: GitHub profile → **Packages** → `stitch-<service>` → **Package settings** → **Change visibility** → Public (six packages: brain, ledger, oracle, library, eyes, web). Then the VPS pulls with no credentials.
4. On the VPS: set `ORIGIN_URL="https://github.com/<owner>/<repo>.git"` and `BUILD_MISSING=0` in `/opt/stitch/deploy.conf`, and `GH_OWNER=<owner, lowercase>` in `/opt/stitch/prod.env`.

## Security headers and routing

`snippets/common.caddy`: `/healthz` (gateway liveness), `/api/*` → `brain:8000` with the prefix stripped, `flush_interval -1` (SSE flushed per write), no compression on `/api`, `request_body max_size 4MB`, a JSON 503 `UPSTREAM_UNAVAILABLE` when the Brain is down, static files with `encode zstd gzip` and long-lived caching for hashed assets. Headers: CSP (script hashes of the static export's inline scripts, `style-src 'unsafe-inline'` for MapLibre and Motion, `worker-src blob:` for MapLibre workers, `connect-src 'self'`), HSTS, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy` (microphone only for self), `Cross-Origin-Opener-Policy`, `X-Frame-Options`. The status endpoint is `/api/organs`.

## Measurements

Image sizes (unpacked, `deploy/bin/check_images.py`; budgets in `deploy/image-budgets.json`):

| Image | Size | Budget |
|---|---|---|
| stitch-brain | 274 MB | 340 MB |
| stitch-ledger | 616 MB | 700 MB |
| stitch-oracle | 663 MB | 720 MB |
| stitch-library | 842 MB (includes e5-small int8 and mMiniLM int8 ONNX, 2 x 118 MB) | 950 MB |
| stitch-eyes | 515 MB | 600 MB |
| stitch-web | 77 MB | 120 MB |

Ledger and Oracle exceed the design's first guesses (500 MB) because of OR-Tools, pandas and pyarrow wheels; the budgets were raised to the measurement plus headroom.

Measured on the VPS, 2026-11-17, images at 884ff75 (Docker `Size`, which counts shared base layers once per image, so it reads higher than `check_images.py`): brain 377 MB, ledger 831 MB, oracle 896 MB, library 1210 MB, eyes 702 MB, web 174 MB. Re-run `check_images.py` on the next build and refresh the table above.

Memory, idle after start (`docker stats --no-stream`, VPS, demo mode, Brain not yet running because brain task 23, the HTTP app, has not landed):

| Service | Idle | Limit (base) | Limit (prod) |
|---|---|---|---|
| library | 817 MiB | 832 MiB | 1280 MiB |
| eyes | 325 MiB | 640 MiB | 640 MiB |
| oracle | 186 MiB | 320 MiB | 320 MiB |
| ledger | 111 MiB | 256 MiB | 256 MiB |
| postgres | 19 MiB | 384 MiB | 384 MiB |
| web | 12 MiB | 64 MiB | 96 MiB |
| brain | not measured | 320 MiB | 320 MiB |
| voice | not measured | 640 MiB | 640 MiB |

The Library idles at 98 % of its base limit, so `compose.prod.yaml` raises it to 1280 MiB on the 16 GB host. On a 4 GB host use `compose.lite.yaml` (no reranker). Peak numbers under a briefing loop are still to be measured (task 13).

## Backup and restore (DEP-R7.4)

The Library index is rebuilt by the seed job, so a backup is a convenience.

```bash
stitch-backup                                   # /opt/stitch/backups/stitch-<UTC>.dump, keeps 4 (weekly cron)
stitch-backup rehearse /opt/stitch/backups/<file>.dump   # restore into a scratch DB and compare row counts
stitch-backup restore /opt/stitch/backups/<file>.dump    # restore into the live DB (--clean)
```

Equivalent raw commands: `docker compose exec -T postgres pg_dump -U stitch_owner -Fc stitch > stitch.dump` and `docker compose exec -T postgres pg_restore -U stitch_owner -d stitch --clean --if-exists < stitch.dump`. The volume-level alternative is a copy of `stitch_pgdata` with Postgres stopped. `caddy_data` can be tarred too; certificates are re-issuable.

## Checks

| Check | Command |
|---|---|
| Compose config for every override | `docker compose -f compose.yaml [-f deploy/compose.<x>.yaml] config -q` |
| Ports and networks (DEP-P4) | `python deploy/bin/check_ports.py` |
| Images (DEP-R2) | `python deploy/bin/check_images.py` |
| Repo hygiene (DEP-P2, P3, R8) | `python deploy/bin/check_repo_hygiene.py` and `uv run python scripts/secret_scan.py --all` |
| Offline smoke (DEP-P5, P6) | `bash deploy/bin/offline_smoke.sh http://127.0.0.1:8080` (CI) or with `COMPOSE_FILES`, `SKIP_RESTART=1` on the VPS |
| Smoke only | `python3 deploy/bin/smoke.py <base url> --allow-disabled voice` |

## Status on the VPS (2026-11-17)

Running at 884ff75 from `/srv/stitch`: web, postgres (seeded: 9 docs, 65 chunks, `already seeded` on rerun), library, ledger, oracle, eyes, all healthy. `http://64.177.59.11/` and `/healthz` return 200. `/api/*` returns the gateway's JSON 503 `UPSTREAM_UNAVAILABLE`, because the Brain package has no HTTP app yet (`python -m stitch_brain.api` fails; brain task 23). The Brain container is stopped so it does not crash-loop. The smoke script and the offline smoke need the Brain and were not run.

Known issue fixed in git, not yet on the VPS: at 884ff75 `init-secrets` fails on every start after the first (no `DAC_OVERRIDE`), so `docker compose up` stops at Postgres. Until the fix is deployed, start services with `up -d --no-deps` in dependency order (postgres, `run --rm --no-deps -T seed`, library, brain, web).
