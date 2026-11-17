#!/bin/bash
# Offline guarantee (DEP-P5, DEP-P6, DEP-R10.1). Run from the repository root against a running
# stack:
#   bash deploy/bin/offline_smoke.sh [base_url]        # default http://127.0.0.1:8080
# Env: COMPOSE_FILES (default "-f compose.yaml"), SMOKE_ARGS (default "--allow-disabled voice"),
#      SKIP_RESTART=1 to skip the down/up seed idempotence leg (production hosts).
#
# 1. Negative control: from brain, library and oracle an HTTPS request to the internet and a DNS
#    lookup of a public name must FAIL (the `core` network is internal: true).
# 2. Positive control: the same probe reaches http://web:8080/healthz on `core`, so a failure in
#    step 1 is the network and not a broken probe.
# 3. deploy/bin/smoke.py: healthz, organs, demo briefing over SSE, evidence, ask.
# 4. Seed idempotence (DEP-P5): chunk count and hash before and after `down` (no -v) and `up`.
set -euo pipefail
BASE="${1:-http://127.0.0.1:8080}"
read -r -a FILES <<< "${COMPOSE_FILES:--f compose.yaml}"
SMOKE_ARGS="${SMOKE_ARGS:---allow-disabled voice}"
dc() { docker compose "${FILES[@]}" "$@" </dev/null; }

probe() {  # probe <service> <url> -> exit 0 if reachable
    dc exec -T "$1" python -c "
import sys, urllib.request
try:
    urllib.request.urlopen('$2', timeout=5)
except Exception as e:
    print(type(e).__name__, e); sys.exit(1)
" >/dev/null 2>&1
}

echo "== 1. negative control (no egress from the core network)"
for svc in brain library oracle; do
    if probe "$svc" "https://example.com/"; then
        echo "FAIL: $svc reached https://example.com (core network has egress)"; exit 1
    fi
    if dc exec -T "$svc" python -c "import socket; socket.getaddrinfo('example.com', 443)" >/dev/null 2>&1; then
        echo "FAIL: $svc resolved example.com"; exit 1
    fi
    echo "ok: $svc has no route or DNS to the internet"
done

echo "== 2. positive control (the probe works on the internal network)"
probe brain "http://web:8080/healthz" || { echo "FAIL: brain cannot reach web on core"; exit 1; }
echo "ok: brain reaches web:8080 on core"

echo "== 3. smoke"
# shellcheck disable=SC2086
python3 deploy/bin/smoke.py "$BASE" $SMOKE_ARGS

chunks() {
    dc exec -T postgres psql -U postgres -d stitch -tA -c \
        "SELECT count(*) || ':' || md5(coalesce(string_agg(chunk_id::text, ',' ORDER BY chunk_id), '')) FROM chunks"
}
if [[ "${SKIP_RESTART:-0}" == "1" ]]; then
    echo "== 4. seed idempotence: skipped (SKIP_RESTART=1); index $(chunks)"
    exit 0
fi
echo "== 4. seed idempotence (down without -v, up)"
before="$(chunks)"
dc down
dc up -d --no-build --wait --wait-timeout 420
after="$(chunks)"
dc logs seed 2>&1 | grep -iE "already seeded|seed_key" | tail -n 2 || true
echo "chunks before: $before"
echo "chunks after:  $after"
[[ "$before" == "$after" && "${before%%:*}" -gt 0 ]] || { echo "FAIL: index changed or empty"; exit 1; }
echo "OFFLINE SMOKE: ok"
