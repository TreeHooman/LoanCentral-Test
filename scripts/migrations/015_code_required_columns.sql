-- Migration 015: columns the code uses that no earlier migration created
--
-- Found by rehearsing launch against a restore of the original bot's database
-- (only `loans` and `users`). Several columns the services depend on had only
-- ever been created by local_db._ensure_column() — i.e. in the SQLite dev and
-- test databases — or by schema.sql's CREATE TABLE, which is skipped when the
-- table already exists. No Postgres migration added them, so on the live
-- database:
--
--   * user_roles.perm_version / reddit_username were missing, and every lender
--     permission check (resolve_user_identity) failed;
--   * loans.payment_timing was missing, and recording any payment failed.
--
-- This lists every column local_db._ensure_column() adds, so Postgres ends up
-- with the same columns the test suite runs against. All additive and safe to
-- re-run.

ALTER TABLE loans
    ADD COLUMN IF NOT EXISTS loan_id TEXT,
    ADD COLUMN IF NOT EXISTS repay_amount NUMERIC,
    ADD COLUMN IF NOT EXISTS repay_date DATE,
    ADD COLUMN IF NOT EXISTS payment_method TEXT,
    ADD COLUMN IF NOT EXISTS borrower_acknowledged_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS borrower_acknowledged_note TEXT,
    ADD COLUMN IF NOT EXISTS notes TEXT,
    ADD COLUMN IF NOT EXISTS interest_amount NUMERIC,
    ADD COLUMN IF NOT EXISTS interest_rate NUMERIC,
    ADD COLUMN IF NOT EXISTS payment_timing TEXT;

ALTER TABLE loan_requests
    ADD COLUMN IF NOT EXISTS lender_note TEXT,
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS reddit_username VARCHAR(100),
    ADD COLUMN IF NOT EXISTS reddit_comment_id VARCHAR(30),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS funded_loan_id INTEGER,
    ADD COLUMN IF NOT EXISTS notes TEXT;

ALTER TABLE user_roles
    ADD COLUMN IF NOT EXISTS verified_lender BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS verified_lender_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS verified_lender_by TEXT,
    ADD COLUMN IF NOT EXISTS verification_note TEXT,
    ADD COLUMN IF NOT EXISTS contact_email TEXT,
    ADD COLUMN IF NOT EXISTS contact_phone TEXT,
    ADD COLUMN IF NOT EXISTS perm_version INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS reddit_username TEXT,
    ADD COLUMN IF NOT EXISTS reddit_username_linked_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS reddit_username_linked_by TEXT;

CREATE INDEX IF NOT EXISTS idx_user_roles_reddit_username ON user_roles(reddit_username);

ALTER TABLE reddit_actions
    ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS last_error TEXT;
