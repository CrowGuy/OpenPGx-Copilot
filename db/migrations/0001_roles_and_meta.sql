-- 0001: roles, schemas and meta.release (ADR-0005, ADR-0006).
-- Run as a superuser with psql. Every migration must be idempotent: all files are re-applied on each run.
-- ponytail: no applied-migrations table; add one when a migration cannot be written idempotently.

-- Roles. Passwords are set outside migrations (server: initdb secrets; dev: db/dev-setup.sh).
SELECT 'CREATE ROLE etl_writer LOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'etl_writer') \gexec
SELECT 'CREATE ROLE analyst_ro LOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'analyst_ro') \gexec

SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database()) \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO etl_writer, analyst_ro', current_database()) \gexec
SELECT format('GRANT CREATE ON DATABASE %I TO etl_writer', current_database()) \gexec

-- Everything etl_writer creates from now on (Release schemas, their tables, gwas views) is readable by analyst_ro.
ALTER DEFAULT PRIVILEGES FOR ROLE etl_writer GRANT USAGE ON SCHEMAS TO analyst_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE etl_writer GRANT SELECT ON TABLES TO analyst_ro;

CREATE SCHEMA IF NOT EXISTS meta AUTHORIZATION etl_writer;
CREATE SCHEMA IF NOT EXISTS gwas AUTHORIZATION etl_writer;
GRANT USAGE ON SCHEMA meta, gwas TO analyst_ro;

SET ROLE etl_writer;

CREATE TABLE IF NOT EXISTS meta.release (
    release_id text PRIMARY KEY CHECK (release_id ~ '^r[0-9]{4}-[0-9]{2}-[0-9]{2}$'),
    status text NOT NULL CHECK (status IN ('loading', 'candidate', 'active', 'retired')),
    created_at timestamptz NOT NULL DEFAULT now(),
    approved_by text,
    approved_at timestamptz
);
-- At most one Active Release.
CREATE UNIQUE INDEX IF NOT EXISTS release_one_active ON meta.release ((true)) WHERE status = 'active';

GRANT SELECT ON ALL TABLES IN SCHEMA meta, gwas TO analyst_ro;

RESET ROLE;
