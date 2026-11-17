#!/bin/bash
# Postgres backup and restore (deploy design 8, DEP-R7.4). The Library index is reproducible
# from the seed job, so this is a convenience, not the only copy.
#
#   backup.sh                      dump to /opt/stitch/backups/stitch-<UTC date>.dump, keep 4
#   backup.sh restore <file>       restore a dump into the running database (--clean)
#   backup.sh rehearse <file>      restore into a scratch database `stitch_restore_check`,
#                                  compare chunk counts with `stitch`, then drop it
# Uses the local socket inside the postgres container (trust auth for local connections only;
# network connections need SCRAM passwords).
set -euo pipefail
STATE_DIR=/opt/stitch
REPO_DIR="${REPO_DIR:-$STATE_DIR/repo}"
DIR="$STATE_DIR/backups"
KEEP=4
pg() { docker compose --project-directory "$REPO_DIR" -f "$REPO_DIR/compose.yaml" exec -T postgres "$@"; }

case "${1-backup}" in
    backup)
        mkdir -p "$DIR"
        out="$DIR/stitch-$(date -u +%Y%m%dT%H%M%SZ).dump"
        pg pg_dump -U stitch_owner -d stitch -Fc > "$out.tmp"
        mv "$out.tmp" "$out"
        echo "backup: $out ($(du -h "$out" | cut -f1))"
        ls -1t "$DIR"/stitch-*.dump | tail -n +$((KEEP + 1)) | xargs -r rm -f
        ;;
    restore)
        f="${2:?usage: backup.sh restore <file>}"
        pg pg_restore -U stitch_owner -d stitch --clean --if-exists --no-owner < "$f"
        echo "restore: $f applied to stitch"
        ;;
    rehearse)
        f="${2:?usage: backup.sh rehearse <file>}"
        pg psql -v ON_ERROR_STOP=1 -U postgres -d postgres -c "DROP DATABASE IF EXISTS stitch_restore_check" >/dev/null
        pg psql -v ON_ERROR_STOP=1 -U postgres -d postgres -c "CREATE DATABASE stitch_restore_check OWNER stitch_owner" >/dev/null
        pg psql -v ON_ERROR_STOP=1 -U postgres -d stitch_restore_check -c "CREATE EXTENSION IF NOT EXISTS vector" >/dev/null
        pg pg_restore -U postgres -d stitch_restore_check --no-owner --role=stitch_owner < "$f"
        q="SELECT string_agg(relname || '=' || n_live_tup, ' ' ORDER BY relname) FROM pg_stat_user_tables"
        a="$(pg psql -tA -U postgres -d stitch -c "ANALYZE" -c "$q" | tail -n1)"
        b="$(pg psql -tA -U postgres -d stitch_restore_check -c "ANALYZE" -c "$q" | tail -n1)"
        pg psql -U postgres -d postgres -c "DROP DATABASE stitch_restore_check" >/dev/null
        echo "live:     $a"
        echo "restored: $b"
        [[ "$a" == "$b" ]] && echo "rehearsal: row counts match" || { echo "rehearsal: MISMATCH"; exit 1; }
        ;;
    *) echo "usage: backup.sh [backup | restore <file> | rehearse <file>]" >&2; exit 2 ;;
esac
