#!/bin/bash
# Stitch deploy entry on the VPS (deploy design 9.2, DEP-R6). Installed root-owned as
# /usr/local/bin/stitch-deploy and used as the SSH forced command of the `deploy` user:
#
#   ~deploy/.ssh/authorized_keys:
#     command="/usr/local/bin/stitch-deploy",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty ssh-ed25519 AAAA... github-actions-deploy
#   /etc/sudoers.d/stitch-deploy:
#     deploy ALL=(root) NOPASSWD: /usr/local/bin/stitch-deploy
#
# Accepted commands (from $SSH_ORIGINAL_COMMAND, or argv when run by root):
#   <40-hex commit sha>   check out that commit, get images tagged with it, migrate and seed,
#                         start, smoke test locally; roll back automatically if the smoke fails
#   rollback              return to the previous release (one command, no rebuild)
#   status                print current and previous release and the service states
# Anything else is refused. `deploy` is not in the docker group: this script is the only thing
# it may run as root (sudo rule above), so a leaked key can only deploy a commit that exists in
# the origin repository, roll back, or read status.
#
# Configuration: /opt/stitch/deploy.conf (shell variables, root-owned), see deploy/README.md.
set -euo pipefail
umask 022

SELF=/usr/local/bin/stitch-deploy
SHA_RE='^[0-9a-f]{40}$'

validate() {
    local arg="${1-}"
    # whitelist the alphabet first: the regex anchors alone let an embedded newline through
    if [[ -z "$arg" || "$arg" == *[!0-9a-z]* || ${#arg} -gt 40 ]]; then
        return 1
    fi
    if [[ "$arg" =~ $SHA_RE ]] || [[ "$arg" == "rollback" ]] || [[ "$arg" == "status" ]]; then
        return 0
    fi
    return 1
}

# --- argument intake ---------------------------------------------------------------------------
if [[ "${1-}" == "--validate" ]]; then
    # self-test hook for CI (prints the verdict, does nothing else)
    if validate "${2-}"; then echo "valid"; exit 0; else echo "invalid"; exit 2; fi
fi

if [[ -n "${SSH_ORIGINAL_COMMAND+x}" ]]; then
    ARG="$SSH_ORIGINAL_COMMAND"
else
    ARG="${1-}"
fi
if ! validate "$ARG"; then
    echo "stitch-deploy: refused; expected a 40-hex commit sha, 'rollback' or 'status'" >&2
    exit 2
fi
if [[ $EUID -ne 0 ]]; then
    exec sudo -n "$SELF" "$ARG"
fi

# --- configuration -----------------------------------------------------------------------------
STATE_DIR=/opt/stitch
CONF="$STATE_DIR/deploy.conf"
REPO_DIR="$STATE_DIR/repo"
ORIGIN_URL="/srv/stitch.git"          # GitHub URL once the repo is public
PROD_ENV="$STATE_DIR/prod.env"
SMOKE_URL="http://127.0.0.1"
SMOKE_ARGS="--allow-disabled voice"
BUILD_MISSING=1                        # build locally when the registry has no image for the sha
WAIT_TIMEOUT=900
# shellcheck disable=SC1090
[[ -f "$CONF" ]] && . "$CONF"
LOG="$STATE_DIR/deploy.log"
mkdir -p "$STATE_DIR/backups"
exec 9>/run/lock/stitch-deploy.lock
if ! flock -w 1800 9; then
    echo "stitch-deploy: another deploy holds the lock" >&2
    exit 75
fi

log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG" >&2; }

compose() {
    (cd "$REPO_DIR" && TAG="$1" docker compose --env-file "$PROD_ENV" \
        -f compose.yaml -f deploy/compose.prod.yaml "${@:2}")
}

read_tag() { [[ -f "$1" ]] && sed -n 's/^TAG=//p' "$1" | head -n1 || true; }

ensure_repo() {
    if [[ ! -d "$REPO_DIR/.git" ]]; then
        git clone --quiet "$ORIGIN_URL" "$REPO_DIR"
    fi
    git -C "$REPO_DIR" remote set-url origin "$ORIGIN_URL"
    git -C "$REPO_DIR" fetch --quiet --prune origin '+refs/heads/*:refs/remotes/origin/*'
}

checkout() {
    local sha="$1"
    if ! git -C "$REPO_DIR" cat-file -e "${sha}^{commit}" 2>/dev/null; then
        log "commit $sha is not in $ORIGIN_URL"
        return 1
    fi
    git -C "$REPO_DIR" checkout --quiet --force --detach "$sha"
}

# Prints "<service> <image>" for every service that has a build section and whose image for
# this sha is not present locally.
missing_buildable() {
    compose "$1" config --format json | python3 -c '
import json, subprocess, sys
cfg = json.load(sys.stdin)
for name, svc in cfg["services"].items():
    if "build" not in svc:
        continue
    have = subprocess.run(["docker", "image", "inspect", svc["image"]],
                          capture_output=True).returncode == 0
    if not have:
        print(name, svc["image"])
'
}

get_images() {
    local sha="$1" missing
    compose "$sha" pull --quiet --ignore-buildable >>"$LOG" 2>&1 || true
    missing="$(missing_buildable "$sha")"
    [[ -z "$missing" ]] && { log "images for $sha present"; return 0; }
    if compose "$sha" pull --quiet >>"$LOG" 2>&1; then
        missing="$(missing_buildable "$sha")"
        [[ -z "$missing" ]] && { log "pulled images for $sha"; return 0; }
    fi
    if [[ "$BUILD_MISSING" != "1" ]]; then
        log "no registry images for $sha and BUILD_MISSING is off"
        return 1
    fi
    log "building locally (nice, sequential): $(echo "$missing" | cut -d' ' -f1 | tr '\n' ' ')"
    local svc img
    while read -r svc img; do
        [[ -z "$svc" ]] && continue
        # one image may serve two services (library and seed); skip it once built
        docker image inspect "$img" >/dev/null 2>&1 && continue
        nice -n 10 bash -c 'cd "$1" && TAG="$2" docker compose --env-file "$3" \
            -f compose.yaml -f deploy/compose.prod.yaml build "$4"' _ \
            "$REPO_DIR" "$sha" "$PROD_ENV" "$svc" >>"$LOG" 2>&1 || {
            log "build of $svc failed"; return 1; }
    done <<< "$missing"
}

smoke() {
    python3 "$REPO_DIR/deploy/bin/smoke.py" "$SMOKE_URL" $SMOKE_ARGS --retries 6 >>"$LOG" 2>&1
}

start() {
    local sha="$1"
    compose "$sha" run --rm seed >>"$LOG" 2>&1 || { log "seed or migration failed"; return 1; }
    compose "$sha" up -d --remove-orphans --wait --wait-timeout "$WAIT_TIMEOUT" >>"$LOG" 2>&1
}

prune() {
    local keep_cur keep_prev
    keep_cur="$(read_tag "$STATE_DIR/current.env")"
    keep_prev="$(read_tag "$STATE_DIR/previous.env")"
    docker image ls --format '{{.Repository}}:{{.Tag}}' | grep '/stitch-' | while read -r ref; do
        tag="${ref##*:}"
        if [[ "$tag" =~ $SHA_RE ]] && [[ "$tag" != "$keep_cur" ]] && [[ "$tag" != "$keep_prev" ]]; then
            docker image rm "$ref" >/dev/null 2>&1 || true
        fi
    done
    docker image prune -f >/dev/null 2>&1 || true
}

do_rollback() {
    local prev
    prev="$(read_tag "$STATE_DIR/previous.env")"
    if [[ -z "$prev" ]]; then
        log "rollback: no previous release recorded"
        return 1
    fi
    local cur
    cur="$(read_tag "$STATE_DIR/current.env")"
    log "rollback: $cur -> $prev"
    ensure_repo
    checkout "$prev"
    compose "$prev" up -d --remove-orphans --wait --wait-timeout "$WAIT_TIMEOUT" >>"$LOG" 2>&1
    echo "TAG=$prev" > "$STATE_DIR/current.env"
    [[ -n "$cur" ]] && echo "TAG=$cur" > "$STATE_DIR/previous.env"
    log "rollback: running $prev"
}

do_deploy() {
    local sha="$1" cur prev_before
    cur="$(read_tag "$STATE_DIR/current.env")"
    prev_before="$(read_tag "$STATE_DIR/previous.env")"
    log "deploy: $sha (current: ${cur:-none})"
    ensure_repo
    checkout "$sha"
    if ! get_images "$sha"; then
        log "deploy: no images for $sha; still running ${cur:-nothing}"
        [[ -n "$cur" ]] && checkout "$cur"
        return 1
    fi
    if ! start "$sha" || ! smoke; then
        log "deploy: $sha failed health or smoke"
        compose "$sha" ps >>"$LOG" 2>&1 || true
        if [[ -n "$cur" && "$cur" != "$sha" ]]; then
            echo "TAG=$sha" > "$STATE_DIR/current.env"
            echo "TAG=$cur" > "$STATE_DIR/previous.env"
            do_rollback || true
            # the failed sha is not kept as a rollback target
            if [[ -n "$prev_before" ]]; then
                echo "TAG=$prev_before" > "$STATE_DIR/previous.env"
            else
                rm -f "$STATE_DIR/previous.env"
            fi
        fi
        return 1
    fi
    if [[ -n "$cur" && "$cur" != "$sha" ]]; then
        echo "TAG=$cur" > "$STATE_DIR/previous.env"
    fi
    echo "TAG=$sha" > "$STATE_DIR/current.env"
    prune
    log "deploy: $sha live"
}

case "$ARG" in
    status)
        echo "current:  $(read_tag "$STATE_DIR/current.env")"
        echo "previous: $(read_tag "$STATE_DIR/previous.env")"
        cur="$(read_tag "$STATE_DIR/current.env")"
        if [[ -n "$cur" ]]; then
            compose "$cur" ps --format 'table {{.Service}}\t{{.Status}}'
        fi
        ;;
    rollback) do_rollback ;;
    *) do_deploy "$ARG" ;;
esac
