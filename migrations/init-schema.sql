-- Bootstrap: create the osint schema before any Alembic migrations run.
-- Execute this once against a fresh database:
--   psql -U osint -d osint -f migrations/init-schema.sql

CREATE SCHEMA IF NOT EXISTS osint;
