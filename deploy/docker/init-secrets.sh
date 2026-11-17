#!/bin/sh
# One-shot job (deploy design 6.2): generate per-deployment Postgres passwords into the `secrets`
# volume on first start. Existing files are kept, so restarts never rotate a password under a
# running database. Nothing is printed except file names.
#   pg_superuser_password  postgres superuser (POSTGRES_PASSWORD_FILE), uid 999, 0400
#   pg_owner_password      stitch_owner (schema owner, seed job),       uid 999, 0400
#   pg_app_password        stitch_app (runtime Library role),           uid 999, 0400
#   pgpass_owner           libpq passfile for the seed job,            uid 10002, 0600
#   pgpass_app             libpq passfile for the Library,             uid 10001, 0600
set -eu
umask 077
dir=/secrets
gen() {
    if [ ! -s "$dir/$1" ]; then
        head -c 48 /dev/urandom | base64 | tr -d '/+=\n' | head -c 40 > "$dir/$1.tmp"
        mv "$dir/$1.tmp" "$dir/$1"
        echo "init-secrets: generated $1"
    else
        echo "init-secrets: kept $1"
    fi
}
gen pg_superuser_password
gen pg_owner_password
gen pg_app_password
printf 'postgres:5432:stitch:stitch_owner:%s\n' "$(cat "$dir/pg_owner_password")" > "$dir/pgpass_owner"
printf 'postgres:5432:stitch:stitch_app:%s\n' "$(cat "$dir/pg_app_password")" > "$dir/pgpass_app"
chown 999:999 "$dir/pg_superuser_password" "$dir/pg_owner_password" "$dir/pg_app_password"
chmod 0400 "$dir/pg_superuser_password" "$dir/pg_owner_password" "$dir/pg_app_password"
chown 10002:10002 "$dir/pgpass_owner"
chown 10001:10001 "$dir/pgpass_app"
chmod 0600 "$dir/pgpass_owner" "$dir/pgpass_app"
chmod 0711 "$dir"
echo "init-secrets: ok"
