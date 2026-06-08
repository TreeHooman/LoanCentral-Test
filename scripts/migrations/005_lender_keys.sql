-- Migration 005: lender API keys
-- Each key grants dashboard access for one lender.
-- Only the SHA-256 hash is stored — the plaintext key is shown once on creation.

CREATE TABLE IF NOT EXISTS lender_keys (
    id          SERIAL PRIMARY KEY,
    username    TEXT NOT NULL,
    key_hash    TEXT NOT NULL UNIQUE,
    label       TEXT,
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_by  TEXT NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    last_used   TIMESTAMP,
    revoked_at  TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_lender_keys_username ON lender_keys(username);
CREATE INDEX IF NOT EXISTS idx_lender_keys_hash     ON lender_keys(key_hash);
