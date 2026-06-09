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
    notes TEXT
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
    perm_version INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_user_roles_role ON user_roles(role);

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

-- Loan requests table — created when bot sees a [REQ] post, funded when lender confirms on dashboard
CREATE TABLE IF NOT EXISTS loan_requests (
    id SERIAL PRIMARY KEY,
    request_id TEXT UNIQUE NOT NULL,         -- e.g. REQ-0042
    borrower TEXT NOT NULL,
    amount NUMERIC NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    repay_amount NUMERIC,                    -- NULL if not stated in post, mandatory before funding
    repay_date DATE,                         -- NULL if not stated in post
    payment_method TEXT,                     -- PayPal, Venmo, etc. if stated
    lender_note TEXT,
    expires_at TIMESTAMP,
    post_date TIMESTAMP NOT NULL,
    thread_link TEXT NOT NULL,
    reddit_post_id TEXT,                     -- raw Reddit post ID for dedup
    status TEXT NOT NULL DEFAULT 'open',     -- open, funded, expired, cancelled
    funded_by TEXT,                          -- lender username, set when funded
    funded_date TIMESTAMP,
    loan_id TEXT,                            -- FK to loans.loan_id once funded
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_loan_requests_status   ON loan_requests(status);
CREATE INDEX IF NOT EXISTS idx_loan_requests_borrower ON loan_requests(borrower);
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
