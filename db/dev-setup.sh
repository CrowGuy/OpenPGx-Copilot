#!/bin/sh
# Dev/test only: create openpgx_test, apply db/migrations to openpgx and openpgx_test, set dev passwords.
# Safe to re-run. Connection comes from the standard PG* environment variables (superuser).
set -eu
export PGOPTIONS="-c client_min_messages=warning"
cd "$(dirname "$0")"
psql -v ON_ERROR_STOP=1 -d openpgx -tAc "SELECT 1 FROM pg_database WHERE datname = 'openpgx_test'" | grep -q 1 \
  || psql -v ON_ERROR_STOP=1 -d openpgx -c 'CREATE DATABASE openpgx_test'
for db in openpgx openpgx_test; do
  for f in migrations/*.sql; do
    psql -v ON_ERROR_STOP=1 -q -d "$db" -f "$f"
  done
done
# Dev passwords only: the port is bound to 127.0.0.1. The server uses secrets (docs/postgres-docker-playbook.md).
psql -v ON_ERROR_STOP=1 -q -d openpgx \
  -c "ALTER ROLE etl_writer PASSWORD 'etl_writer'" \
  -c "ALTER ROLE analyst_ro PASSWORD 'analyst_ro'"
echo "dev database ready"
