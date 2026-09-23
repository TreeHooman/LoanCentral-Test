-- LoanCentral dashboard migration
-- Safe to run more than once on an existing PostgreSQL database.

ALTER TABLE loans
    ADD COLUMN IF NOT EXISTS loan_id TEXT UNIQUE,
    ADD COLUMN IF NOT EXISTS repay_amount NUMERIC,
    ADD COLUMN IF NOT EXISTS repay_date DATE,
    ADD COLUMN IF NOT EXISTS payment_method TEXT,
    ADD COLUMN IF NOT EXISTS borrower_acknowledged_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS borrower_acknowledged_note TEXT,
    ADD COLUMN IF NOT EXISTS notes TEXT;

CREATE INDEX IF NOT EXISTS idx_loans_lender ON loans(lender);
CREATE INDEX IF NOT EXISTS idx_loans_borrower ON loans(borrower);
CREATE INDEX IF NOT EXISTS idx_loans_status ON loans(status);
CREATE INDEX IF NOT EXISTS idx_loans_date_created ON loans(date_created);

CREATE TABLE IF NOT EXISTS user_roles (
    username TEXT PRIMARY KEY,
    role TEXT NOT NULL DEFAULT 'borrower',
    subscription_status TEXT NOT NULL DEFAULT 'free',
    created_at TIMESTAMP DEFAULT NOW(),
    last_login TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_user_roles_role ON user_roles(role);

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

-- loan_requests uses the current column names (borrower_username,
-- request_status, thread_url, ...). This migration originally created the
-- table with the pre-rename names (borrower, status, thread_link) and indexed
-- them; migrations/migrate_loan_requests.py renamed them later. Against a
-- database that never had the table — the original bot's database, which has
-- only loans and users — that meant either order failed: after the bot's
-- startup schema check created the current table, the index on "status" did
-- not exist; before it, this created the old shape and everything newer
-- (migration 013, the services) failed on it.
--
-- Databases that already ran this file keep their table and their index names
-- (IF NOT EXISTS matches by name), so this is a no-op for them.
CREATE TABLE IF NOT EXISTS loan_requests (
    id SERIAL PRIMARY KEY,
    request_id VARCHAR(20) NOT NULL UNIQUE,
    borrower_username VARCHAR(100) NOT NULL,
    reddit_username VARCHAR(100),
    requested_amount NUMERIC(12,2),
    requested_repayment_amount NUMERIC(12,2),
    requested_due_date DATE,
    request_status VARCHAR(30) NOT NULL DEFAULT 'open',
    thread_url TEXT,
    reddit_post_id VARCHAR(30),
    reddit_comment_id VARCHAR(30),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    funded_loan_id INTEGER REFERENCES loans(id) ON DELETE SET NULL,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_loan_requests_status ON loan_requests(request_status);
CREATE INDEX IF NOT EXISTS idx_loan_requests_borrower ON loan_requests(borrower_username);
CREATE INDEX IF NOT EXISTS idx_loan_requests_request_id ON loan_requests(request_id);

ALTER TABLE loan_requests
    ADD COLUMN IF NOT EXISTS lender_note TEXT,
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;

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
