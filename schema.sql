-- LoanCentral Database Schema
-- This file contains the complete database schema for the LoanCentral bot

-- Create loans table to store information about individual loans
CREATE TABLE IF NOT EXISTS loans (
    id SERIAL PRIMARY KEY,
    loan_id TEXT UNIQUE,
    lender TEXT NOT NULL,
    borrower TEXT NOT NULL,
    amount NUMERIC NOT NULL,
    currency TEXT NOT NULL,
    date_created TIMESTAMP NOT NULL,
    original_thread TEXT NOT NULL,
    status TEXT DEFAULT 'confirmed',  -- confirmed, partially_repaid, repaid, unpaid, refunded, disputed
    amount_repaid NUMERIC DEFAULT 0,
    repay_amount NUMERIC,
    last_updated TIMESTAMP,
    repay_date DATE,
    payment_method TEXT,
    borrower_acknowledged_at TIMESTAMP,
    borrower_acknowledged_note TEXT,
    notes TEXT,
    interest_amount NUMERIC,
    interest_rate NUMERIC,
    payment_timing TEXT                       -- 'early', 'late', 'on_time', NULL
);

-- Create users table to store aggregate statistics about users
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    loans_as_borrower INTEGER DEFAULT 0,
    loans_as_lender INTEGER DEFAULT 0,
    amount_borrowed NUMERIC DEFAULT 0,
    amount_lent NUMERIC DEFAULT 0,
    amount_repaid NUMERIC DEFAULT 0,
    unpaid_loans INTEGER DEFAULT 0,
    unpaid_amount NUMERIC DEFAULT 0,
    last_updated TIMESTAMP
);

-- User roles table for dashboard access control
CREATE TABLE IF NOT EXISTS user_roles (
    username TEXT PRIMARY KEY,
    role TEXT NOT NULL DEFAULT 'borrower',       -- 'admin', 'mod', 'lender', 'borrower'
    subscription_status TEXT NOT NULL DEFAULT 'free',  -- 'free', 'paid'
    created_at TIMESTAMP DEFAULT NOW(),
    last_login TIMESTAMP,
    verified_lender BOOLEAN NOT NULL DEFAULT FALSE,
    verified_lender_at TIMESTAMP,
    verified_lender_by TEXT,
    verification_note TEXT,
    contact_email TEXT,
    contact_phone TEXT,
    perm_version INTEGER NOT NULL DEFAULT 0,
    reddit_username TEXT,
    reddit_username_linked_at TIMESTAMP,
    reddit_username_linked_by TEXT,
    google_sub TEXT,          -- Google's permanent account ID (sign-in)
    google_email TEXT,        -- display only
    google_linked_at TIMESTAMP,
    legacy_lender BOOLEAN NOT NULL DEFAULT FALSE,   -- admin-granted (migration 019)
    legacy_granted_by TEXT,
    legacy_granted_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_user_roles_role ON user_roles(role);
CREATE INDEX IF NOT EXISTS idx_user_roles_reddit_username ON user_roles(reddit_username);
CREATE INDEX IF NOT EXISTS idx_user_roles_verified_lender ON user_roles(verified_lender);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_loans_lender ON loans(lender);
CREATE INDEX IF NOT EXISTS idx_loans_borrower ON loans(borrower);
CREATE INDEX IF NOT EXISTS idx_loans_status ON loans(status);
CREATE INDEX IF NOT EXISTS idx_loans_date_created ON loans(date_created);

-- Loan attachments (photos, files uploaded via dashboard)
CREATE TABLE IF NOT EXISTS loan_attachments (
    id SERIAL PRIMARY KEY,
    loan_id TEXT NOT NULL,
    uploaded_by TEXT NOT NULL,
    filename TEXT NOT NULL,
    original_name TEXT NOT NULL,
    file_size INTEGER,
    mime_type TEXT,
    uploaded_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_attachments_loan_id ON loan_attachments(loan_id);

-- Loan requests table — created when bot sees a [REQ] post, funded when lender confirms on dashboard.
-- Canonical shape: matches services._ensure_loan_requests_table and prod
-- (prod was renamed from the old bot columns by migrations/migrate_loan_requests.py).
CREATE TABLE IF NOT EXISTS loan_requests (
    id SERIAL PRIMARY KEY,
    request_id VARCHAR(20) NOT NULL UNIQUE,      -- e.g. REQ-0042
    borrower_username VARCHAR(100) NOT NULL,
    reddit_username VARCHAR(100),
    requested_amount NUMERIC(12,2),
    requested_repayment_amount NUMERIC(12,2),
    requested_due_date DATE,
    request_status VARCHAR(30) NOT NULL DEFAULT 'open',  -- open, funded, expired, cancelled
    thread_url TEXT,
    reddit_post_id VARCHAR(30),                  -- raw Reddit post ID for dedup
    reddit_comment_id VARCHAR(30),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    funded_loan_id INTEGER REFERENCES loans(id) ON DELETE SET NULL,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_lr_borrower ON loan_requests (lower(borrower_username));
CREATE INDEX IF NOT EXISTS idx_lr_status   ON loan_requests (request_status);
CREATE INDEX IF NOT EXISTS idx_lr_created  ON loan_requests (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_loan_requests_request_id ON loan_requests(request_id);

-- Immutable activity/audit events for bot, dashboard, and mod actions
CREATE TABLE IF NOT EXISTS audit_events (
    id SERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    actor TEXT,
    actor_role TEXT,
    target_user TEXT,
    loan_id TEXT,
    request_id TEXT,
    source TEXT NOT NULL DEFAULT 'system',
    details JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_events_created_at ON audit_events(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_events_type ON audit_events(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_events_actor ON audit_events(actor);
CREATE INDEX IF NOT EXISTS idx_audit_events_target_user ON audit_events(target_user);

-- Lender verification applications reviewed by mods.
-- Private evidence is summarized here; sensitive files should stay in uploads.
CREATE TABLE IF NOT EXISTS verification_applications (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL,
    requested_role TEXT NOT NULL DEFAULT 'lender',
    status TEXT NOT NULL DEFAULT 'pending', -- pending, approved, denied
    public_note TEXT,
    private_note TEXT,
    reviewer TEXT,
    review_note TEXT,
    submitted_at TIMESTAMP DEFAULT NOW(),
    reviewed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_verification_status ON verification_applications(status);
CREATE INDEX IF NOT EXISTS idx_verification_username ON verification_applications(username);

-- Outbound Reddit actions staged for review/execution.
-- This queue lets reminders, bans, and flair sync be audited before any live API call.
CREATE TABLE IF NOT EXISTS reddit_actions (
    id SERIAL PRIMARY KEY,
    action_type TEXT NOT NULL,              -- reminder_comment, lender_dm, ban_user, flair_sync
    status TEXT NOT NULL DEFAULT 'queued',  -- queued, sent, skipped, failed, cancelled
    target_user TEXT,
    loan_id TEXT,
    request_id TEXT,
    subreddit TEXT,
    payload JSONB,
    reason TEXT,
    created_by TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_reddit_actions_status ON reddit_actions(status);
CREATE INDEX IF NOT EXISTS idx_reddit_actions_type ON reddit_actions(action_type);
CREATE INDEX IF NOT EXISTS idx_reddit_actions_target ON reddit_actions(target_user);

-- Structured audit log (distinct from audit_events; tracks dashboard mod actions)
CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    actor_username TEXT NOT NULL,
    actor_role TEXT NOT NULL,
    action_type TEXT NOT NULL,
    target_type TEXT,
    target_id TEXT,
    old_value_json TEXT,
    new_value_json TEXT,
    ip_address TEXT,
    metadata_json TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_actor ON audit_logs(actor_username);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action_type);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_logs_target ON audit_logs(target_type, target_id);

-- Loan timeline events (immutable per-loan activity feed)
CREATE TABLE IF NOT EXISTS loan_events (
    id SERIAL PRIMARY KEY,
    loan_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor_username TEXT,
    details TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_loan_events_loan_id ON loan_events(loan_id);
CREATE INDEX IF NOT EXISTS idx_loan_events_created ON loan_events(created_at);

-- In-app notifications
CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL,
    notification_type TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT,
    read BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notifications_username ON notifications(username);
CREATE INDEX IF NOT EXISTS idx_notifications_unread ON notifications(username, read);

-- Sprint 8: User notification preferences
CREATE TABLE IF NOT EXISTS notification_preferences (
    username TEXT PRIMARY KEY,
    due_date_reminders BOOLEAN NOT NULL DEFAULT TRUE,
    status_updates BOOLEAN NOT NULL DEFAULT TRUE,
    verification_updates BOOLEAN NOT NULL DEFAULT TRUE,
    dispute_updates BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Sprint 8: User feedback submissions (bugs, suggestions, feature requests)
CREATE TABLE IF NOT EXISTS feedback_submissions (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL,
    category TEXT NOT NULL,          -- 'bug', 'suggestion', 'feature_request'
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',  -- 'open', 'reviewed', 'completed', 'duplicate'
    reviewed_by TEXT,
    reviewer_note TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_feedback_username ON feedback_submissions(username);
CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback_submissions(status);
CREATE INDEX IF NOT EXISTS idx_feedback_category ON feedback_submissions(category);

-- Sprint 8: Lightweight operational analytics
CREATE TABLE IF NOT EXISTS analytics_events (
    id SERIAL PRIMARY KEY,
    username TEXT,
    event_type TEXT NOT NULL,   -- 'page_view', 'search', 'verification_submit', 'feedback_submit'
    page TEXT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analytics_event_type ON analytics_events(event_type);
CREATE INDEX IF NOT EXISTS idx_analytics_created_at ON analytics_events(created_at);

-- Sprint 10: Internal announcements / platform notices
CREATE TABLE IF NOT EXISTS announcements (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    author TEXT NOT NULL,
    pinned BOOLEAN NOT NULL DEFAULT FALSE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_announcements_active ON announcements(active);
CREATE INDEX IF NOT EXISTS idx_announcements_created ON announcements(created_at);

-- Global platform bans. The DB is the source of truth (docs/SECURITY.md rule 2);
-- a Reddit subreddit ban is a separate, operational action queued through
-- reddit_actions. One row per ban episode, so the history is preserved when a
-- user is unbanned and later banned again.
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
-- At most one active ban per user, so repeated ban actions are idempotent
-- rather than piling up rows that all have to be cleared to unban.
CREATE UNIQUE INDEX IF NOT EXISTS uq_banned_users_active
    ON banned_users (lower(username)) WHERE active;

-- Borrower OTP login sessions (migration 006). Present here too so the SQLite
-- dev/test database can exercise borrower login, which it previously could not.
CREATE TABLE IF NOT EXISTS borrower_otp_sessions (
    id           SERIAL PRIMARY KEY,
    username     TEXT        NOT NULL,
    otp_hash     TEXT        NOT NULL,
    contact      TEXT        NOT NULL,
    contact_type TEXT        NOT NULL,
    expires_at   TIMESTAMP   NOT NULL,
    used         BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMP   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_otp_username ON borrower_otp_sessions (username, used, expires_at);

-- Borrower read-only magic links (migration 007).
CREATE TABLE IF NOT EXISTS borrower_magic_links (
    id          SERIAL PRIMARY KEY,
    username    TEXT        NOT NULL,
    token_hash  TEXT        NOT NULL UNIQUE,
    expires_at  TIMESTAMP   NOT NULL,
    used        BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMP   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_magic_link_token ON borrower_magic_links (token_hash, used, expires_at);

-- Lender API keys (migration 005). Present here too so the SQLite dev/test
-- database can exercise key management, which it previously could not.
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

-- One-time links the bot DMs for `$login`: following one proves the Reddit
-- name and lets the person connect a Google account (migration 017).
CREATE TABLE IF NOT EXISTS account_setup_links (
    id SERIAL PRIMARY KEY,
    reddit_username TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL,
    used_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_setup_links_user ON account_setup_links(reddit_username, created_at);

-- `$loan` offers awaiting the borrower's `$confirm` (migration 018). Not loans:
-- nothing here reaches loans, stats or history until it is confirmed.
CREATE TABLE IF NOT EXISTS loan_offers (
    id SERIAL PRIMARY KEY,
    lender TEXT NOT NULL,
    borrower TEXT NOT NULL,
    amount NUMERIC(12,2) NOT NULL,
    currency TEXT NOT NULL,
    thread_url TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    loan_db_id TEXT,              -- the loan's public ID (loans.loan_id)
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL,
    confirmed_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_loan_offers_borrower_open ON loan_offers(borrower, status);
