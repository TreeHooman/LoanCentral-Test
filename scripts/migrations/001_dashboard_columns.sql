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

CREATE TABLE IF NOT EXISTS loan_requests (
    id SERIAL PRIMARY KEY,
    request_id TEXT UNIQUE NOT NULL,
    borrower TEXT NOT NULL,
    amount NUMERIC NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    repay_amount NUMERIC,
    repay_date DATE,
    lender_note TEXT,
    expires_at TIMESTAMP,
    payment_method TEXT,
    post_date TIMESTAMP NOT NULL,
    thread_link TEXT NOT NULL,
    reddit_post_id TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    funded_by TEXT,
    funded_date TIMESTAMP,
    loan_id TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_loan_requests_status ON loan_requests(status);
CREATE INDEX IF NOT EXISTS idx_loan_requests_borrower ON loan_requests(borrower);
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
