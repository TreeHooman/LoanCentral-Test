-- Migration 009: Loan event timeline
CREATE TABLE IF NOT EXISTS loan_events (
    id             SERIAL PRIMARY KEY,
    loan_id        TEXT NOT NULL,
    event_type     TEXT NOT NULL,
    actor_username TEXT,
    details        TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_loan_events_loan    ON loan_events (loan_id);
CREATE INDEX IF NOT EXISTS idx_loan_events_created ON loan_events (created_at DESC);
