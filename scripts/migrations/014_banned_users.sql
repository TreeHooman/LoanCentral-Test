-- Migration 014: global platform bans
--
-- There was no ban system at all: no table, no check in any decorator, and no
-- is_banned anywhere in the codebase. "Ban" meant queueing a ban_user row in
-- reddit_actions for a moderator to perform by hand on Reddit, which recorded
-- an intention but never stopped the account using LoanCentral.
--
-- Additive: creates one table and its indexes, touches nothing existing.

CREATE TABLE IF NOT EXISTS banned_users (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL,
    reason TEXT,
    banned_by TEXT NOT NULL,
    banned_at TIMESTAMP NOT NULL DEFAULT NOW(),
    unbanned_by TEXT,
    unbanned_at TIMESTAMP,
    unban_reason TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    loan_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_banned_users_username ON banned_users(lower(username));
CREATE UNIQUE INDEX IF NOT EXISTS uq_banned_users_active
    ON banned_users (lower(username)) WHERE active;
