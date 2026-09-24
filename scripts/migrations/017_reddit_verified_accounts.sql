-- Migration 017: accounts proven through Reddit, signed in with Google
--
-- Sign-in without keys or emailed codes:
--   1. On Reddit, `$login` makes the bot DM a one-time setup link to the
--      commenter. Only the real account can read its DMs, so following the link
--      proves the Reddit name.
--   2. The link opens "create your account", where the person connects a
--      Google account. That link is stored here.
--   3. From then on they sign in with Google. Losing the Google account means
--      `$login` again, which replaces the link.
--
-- google_sub is Google's permanent account ID; the address is kept for display
-- only, since a Gmail address can change or be reused. One Google account can
-- belong to one LoanCentral account.
--
-- Additive: new columns, a new table, indexes.

ALTER TABLE user_roles
    ADD COLUMN IF NOT EXISTS google_sub       TEXT,
    ADD COLUMN IF NOT EXISTS google_email     TEXT,
    ADD COLUMN IF NOT EXISTS google_linked_at TIMESTAMP;

CREATE UNIQUE INDEX IF NOT EXISTS uq_user_roles_google_sub
    ON user_roles (google_sub) WHERE google_sub IS NOT NULL;

CREATE TABLE IF NOT EXISTS account_setup_links (
    id              SERIAL PRIMARY KEY,
    reddit_username TEXT      NOT NULL,
    token_hash      TEXT      NOT NULL UNIQUE,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMP NOT NULL,
    used_at         TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_setup_links_user
    ON account_setup_links (reddit_username, created_at);
