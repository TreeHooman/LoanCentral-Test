-- Migration 007: Borrower magic link tokens (read-only dashboard access)
CREATE TABLE IF NOT EXISTS borrower_magic_links (
    id          SERIAL PRIMARY KEY,
    username    TEXT        NOT NULL,
    token_hash  TEXT        NOT NULL UNIQUE,
    expires_at  TIMESTAMP   NOT NULL,
    used        BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMP   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_magic_link_token ON borrower_magic_links (token_hash, used, expires_at);
