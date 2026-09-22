-- Migration 012: migration tracking
--
-- Until now run_migrations.py re-executed every file on every run. That was
-- safe only by convention (every statement happened to be IF NOT EXISTS) and
-- left no record of what the database had actually seen. This table is that
-- record.
--
-- Migrations 001-011 are backfilled as applied by the runner the first time it
-- sees an existing database, because their effects are already present.

CREATE TABLE IF NOT EXISTS schema_migrations (
    filename    TEXT        PRIMARY KEY,
    checksum    TEXT        NOT NULL,
    applied_at  TIMESTAMP   NOT NULL DEFAULT NOW(),
    applied_by  TEXT
);
