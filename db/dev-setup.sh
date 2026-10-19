#!/bin/sh
# Dev/test only: create openpgx_test, apply db/migrations to openpgx and openpgx_test, set dev passwords.
# With a worktree name, create and migrate only openpgx_test_<name>: that worktree's own test database, so parallel
# sessions don't reset each other's, and a branch's unmerged migrations never reach openpgx or openpgx_test.
# Safe to re-run. Connection comes from the standard PG* environment variables (superuser).
set -eu
export PGOPTIONS="-c client_min_messages=warning"
cd "$(dirname "$0")"
test_db=openpgx_test
dbs="openpgx openpgx_test"
if [ $# -gt 0 ]; then
  case $1 in '' | *[!A-Za-z0-9_-]*) echo "worktree name: letters, digits, _ and - only" >&2; exit 2 ;; esac
  test_db=openpgx_test_$1
  dbs=$test_db
fi
psql -v ON_ERROR_STOP=1 -d openpgx -tAc "SELECT 1 FROM pg_database WHERE datname = '$test_db'" | grep -q 1 \
  || psql -v ON_ERROR_STOP=1 -d openpgx -c "CREATE DATABASE \"$test_db\""
for db in $dbs; do
  for f in migrations/*.sql; do
    psql -v ON_ERROR_STOP=1 -q -d "$db" -f "$f"
  done
done
# Dev passwords only: the port is bound to 127.0.0.1. The server uses secrets (docs/postgres-docker-playbook.md).
psql -v ON_ERROR_STOP=1 -q -d openpgx \
  -c "ALTER ROLE etl_writer PASSWORD 'etl_writer'" \
  -c "ALTER ROLE analyst_ro PASSWORD 'analyst_ro'"
echo "dev database ready"
