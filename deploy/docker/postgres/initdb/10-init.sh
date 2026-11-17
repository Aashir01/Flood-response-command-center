#!/bin/sh
# Postgres first-start init (deploy design 6.3). Runs once, on an empty data directory, as the
# postgres user inside the official entrypoint. Passwords come from the `secrets` volume.
#   stitch_owner  owns the public schema; used by the seed job (migrations and seeding)
#   stitch_app    runtime role for the Library: CONNECT, schema USAGE, SELECT on tables only
set -eu
owner_pw="$(cat /secrets/pg_owner_password)"
app_pw="$(cat /secrets/pg_app_password)"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v owner_pw="$owner_pw" -v app_pw="$app_pw" -v db="$POSTGRES_DB" <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;
CREATE ROLE stitch_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'owner_pw';
CREATE ROLE stitch_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'app_pw';
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE :"db" TO stitch_owner;
GRANT CONNECT ON DATABASE :"db" TO stitch_app;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO stitch_owner;
GRANT USAGE ON SCHEMA public TO stitch_app;
ALTER DEFAULT PRIVILEGES FOR ROLE stitch_owner IN SCHEMA public GRANT SELECT ON TABLES TO stitch_app;
ALTER DEFAULT PRIVILEGES FOR ROLE stitch_owner IN SCHEMA public GRANT SELECT ON SEQUENCES TO stitch_app;
ALTER ROLE stitch_app SET default_transaction_read_only = on;
SQL
echo "stitch init: extension vector, roles stitch_owner and stitch_app created"
