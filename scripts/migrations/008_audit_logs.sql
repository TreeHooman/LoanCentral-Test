-- Migration 008: Audit log table
CREATE TABLE IF NOT EXISTS audit_logs (
    id              SERIAL PRIMARY KEY,
    actor_username  TEXT NOT NULL,
    actor_role      TEXT NOT NULL DEFAULT 'unknown',
    action_type     TEXT NOT NULL,
    target_type     TEXT,
    target_id       TEXT,
    old_value_json  JSONB,
    new_value_json  JSONB,
    ip_address      TEXT,
    metadata_json   JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_actor    ON audit_logs (actor_username);
CREATE INDEX IF NOT EXISTS idx_audit_action   ON audit_logs (action_type);
CREATE INDEX IF NOT EXISTS idx_audit_target   ON audit_logs (target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_audit_created  ON audit_logs (created_at DESC);
