-- Migration 018: loan offers awaiting the borrower's $confirm
--
-- `$loan` on Reddit is an offer, not a loan: the borrower must `$confirm` it
-- before anything reaches their record (as the original bot worked). Without
-- this, any flaired lender could put a debt on anyone's history.
--
-- An offer lives here until it is confirmed (then it points at the loan),
-- or expires. It never appears in loans, stats or history.
--
-- Additive: one new table and an index.

CREATE TABLE IF NOT EXISTS loan_offers (
    id              SERIAL PRIMARY KEY,
    lender          TEXT          NOT NULL,
    borrower        TEXT          NOT NULL,
    amount          NUMERIC(12,2) NOT NULL,
    currency        TEXT          NOT NULL,
    thread_url      TEXT,
    status          TEXT          NOT NULL DEFAULT 'open',   -- open | confirmed | expired
    loan_db_id      INTEGER,
    created_at      TIMESTAMP     NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMP     NOT NULL,
    confirmed_at    TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_loan_offers_borrower_open
    ON loan_offers (borrower, status);
