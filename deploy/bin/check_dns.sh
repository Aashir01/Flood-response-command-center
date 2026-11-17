#!/bin/bash
# Switch the gateway from plain HTTP on the IP to the domain with automatic HTTPS as soon as the
# A record resolves to this host (deploy design 5.1, 10 step 8-9). Installed as
# /usr/local/bin/stitch-check-dns and run by cron every 5 minutes; a no-op once switched.
#
#   stitch-check-dns            check, and switch when DNS is ready
#   stitch-check-dns --dry-run  only report what it would do
#
# Steps when the A record answers PUBLIC_IP on both 1.1.1.1 and 8.8.8.8 (and no AAAA points
# elsewhere):
#   1. SITE_ADDRESS=<domain> in /opt/stitch/prod.env (backup kept as prod.env.bak);
#   2. recreate only the `web` container (Caddy reads the new site address, obtains the
#      certificate over HTTP-01/TLS-ALPN-01 on ports 80/443);
#   3. wait up to 3 minutes for https://<domain>/healthz; on success set SMOKE_URL in
#      /opt/stitch/deploy.conf; on failure restore SITE_ADDRESS=:80 so the site stays reachable.
set -euo pipefail

STATE_DIR=/opt/stitch
CONF="$STATE_DIR/deploy.conf"
PROD_ENV="$STATE_DIR/prod.env"
REPO_DIR="$STATE_DIR/repo"
DOMAIN="stitch.aashirnoman.dev"
PUBLIC_IP=""
# shellcheck disable=SC1090
[[ -f "$CONF" ]] && . "$CONF"
DRY=0
[[ "${1-}" == "--dry-run" ]] && DRY=1

log() { echo "$(date -u +%FT%TZ) check-dns: $*"; }

current_site="$(sed -n 's/^SITE_ADDRESS=//p' "$PROD_ENV" | tail -n1)"
if [[ "$current_site" == "$DOMAIN" ]]; then
    exit 0   # already switched
fi
# back off for an hour after a failed issuance (Let's Encrypt limits failed validations)
if [[ -f "$STATE_DIR/dns-switch-failed" && $DRY -eq 0 ]]; then
    last="$(cat "$STATE_DIR/dns-switch-failed")"
    if (( $(date +%s) - last < 3600 )); then
        exit 0
    fi
fi
if [[ -z "$PUBLIC_IP" ]]; then
    log "PUBLIC_IP is not set in $CONF"
    exit 1
fi

resolve() {  # resolve <type> <server>
    if command -v dig >/dev/null 2>&1; then
        dig +short +time=3 +tries=1 "$1" "$DOMAIN" "@$2" | grep -v '\.$' || true
    else
        python3 - "$1" "$2" "$DOMAIN" <<'PY'
import socket, struct, sys, random
qtype = {"A": 1, "AAAA": 28}[sys.argv[1]]
server, name = sys.argv[2], sys.argv[3]
qid = random.randint(0, 65535)
q = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0)
q += b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\0"
q += struct.pack(">HH", qtype, 1)
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(3)
try:
    s.sendto(q, (server, 53)); data = s.recv(2048)
except OSError:
    sys.exit(0)
an = struct.unpack(">H", data[6:8])[0]; i = len(q)
for _ in range(an):
    i += 2 if data[i] & 0xC0 == 0xC0 else data.index(b"\0", i) + 1 - i
    t, _c, _ttl, ln = struct.unpack(">HHIH", data[i:i + 10]); i += 10
    rd = data[i:i + ln]; i += ln
    if t == 1: print(socket.inet_ntoa(rd))
    if t == 28: print(socket.inet_ntop(socket.AF_INET6, rd))
PY
    fi
}

a1="$(resolve A 1.1.1.1 | sort | tr '\n' ' ')"
a2="$(resolve A 8.8.8.8 | sort | tr '\n' ' ')"
aaaa="$(resolve AAAA 1.1.1.1 | tr '\n' ' ')"
if [[ "${a1% }" != "$PUBLIC_IP" || "${a2% }" != "$PUBLIC_IP" ]]; then
    log "not ready: A via 1.1.1.1='${a1% }' via 8.8.8.8='${a2% }' (want $PUBLIC_IP)"
    exit 0
fi
if [[ -n "${aaaa// /}" ]]; then
    log "not switching: an AAAA record exists ('${aaaa% }'); this host does not serve IPv6. Remove it at name.com."
    exit 0
fi
log "DNS ready: $DOMAIN -> $PUBLIC_IP"
if [[ $DRY -eq 1 ]]; then
    log "dry run: would set SITE_ADDRESS=$DOMAIN and recreate web"
    exit 0
fi

exec 9>/run/lock/stitch-deploy.lock
flock -w 1800 9

cur_tag="$(sed -n 's/^TAG=//p' "$STATE_DIR/current.env" 2>/dev/null | head -n1)"
files="-f compose.yaml -f deploy/compose.prod.yaml"
for f in ${COMPOSE_OVERRIDES-}; do
    [[ "$f" =~ ^deploy/compose\.[a-z]+\.yaml$ ]] && files="$files -f $f"
done
web_up() {
    # shellcheck disable=SC2086
    (cd "$REPO_DIR" && TAG="$cur_tag" docker compose --env-file "$PROD_ENV" \
        $files up -d --no-deps --wait web)
}
# Caddy needs 443/tcp (TLS-ALPN-01, HTTPS) and 443/udp (HTTP/3) open in UFW before it asks
# for a certificate. vps_setup.sh opens them; this keeps the switch safe if they were removed.
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q '^Status: active'; then
    ufw allow 443/tcp >/dev/null
    ufw allow 443/udp >/dev/null
    log "ufw: 443/tcp and 443/udp allowed"
fi
set_site() {
    if grep -q '^SITE_ADDRESS=' "$PROD_ENV"; then
        sed -i "s|^SITE_ADDRESS=.*|SITE_ADDRESS=$1|" "$PROD_ENV"
    else
        echo "SITE_ADDRESS=$1" >> "$PROD_ENV"
    fi
}

cp -p "$PROD_ENV" "$PROD_ENV.bak"
set_site "$DOMAIN"
web_up
for _ in $(seq 1 36); do
    if curl -fsS --max-time 5 "https://$DOMAIN/healthz" >/dev/null 2>&1; then
        log "HTTPS live: https://$DOMAIN/healthz"
        if grep -q '^SMOKE_URL=' "$CONF"; then
            sed -i "s|^SMOKE_URL=.*|SMOKE_URL=https://$DOMAIN|" "$CONF"
        else
            echo "SMOKE_URL=https://$DOMAIN" >> "$CONF"
        fi
        exit 0
    fi
    sleep 5
done
log "certificate not obtained within 3 minutes; back to plain HTTP on the IP (retry in 1 h)"
date +%s > "$STATE_DIR/dns-switch-failed"
docker logs --tail 30 stitch-web-1 2>&1 | grep -iE 'acme|certificate|error' | tail -n 10 || true
set_site ":80"
web_up
exit 1
