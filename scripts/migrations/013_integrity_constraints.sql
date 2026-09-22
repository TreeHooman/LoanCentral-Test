-- Migration 013: database-level integrity constraints
--
-- Until now every invariant lived in Python (docs/DATA_MODEL.md calls them
-- "enforced in services.py, not DB constraints"). A missed code path therefore
-- wrote a bad row silently. These constraints make the worst ones impossible.
--
-- Data safety: every CHECK is added NOT VALID, so it applies to new and updated
-- rows but does not scan or reject existing data. Run
-- `python scripts/check_db_integrity.py` to find pre-existing violations, fix
-- them, then run migration 014 to VALIDATE. Nothing here rewrites or deletes
-- data, and every statement is safe to re-run.

-- --------------------------------------------------------------------------
-- loan_requests: one request per Reddit post, one loan per request
-- --------------------------------------------------------------------------

-- save_loan_request dedupes by SELECT-then-INSERT, which is racy: two
-- near-simultaneous imports of the same post both see "not found" and insert.
CREATE UNIQUE INDEX IF NOT EXISTS uq_lr_reddit_post_id
    ON loan_requests (reddit_post_id)
    WHERE reddit_post_id IS NOT NULL;

-- Stops two requests claiming the same loan record.
CREATE UNIQUE INDEX IF NOT EXISTS uq_lr_funded_loan_id
    ON loan_requests (funded_loan_id)
    WHERE funded_loan_id IS NOT NULL;

-- --------------------------------------------------------------------------
-- loans: public ID uniqueness and money sanity
-- --------------------------------------------------------------------------

CREATE UNIQUE INDEX IF NOT EXISTS uq_loans_loan_id
    ON loans (loan_id)
    WHERE loan_id IS NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_loans_amount_positive') THEN
        ALTER TABLE loans ADD CONSTRAINT ck_loans_amount_positive
            CHECK (amount > 0) NOT VALID;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_loans_repaid_non_negative') THEN
        ALTER TABLE loans ADD CONSTRAINT ck_loans_repaid_non_negative
            CHECK (amount_repaid >= 0) NOT VALID;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_loans_parties_differ') THEN
        ALTER TABLE loans ADD CONSTRAINT ck_loans_parties_differ
            CHECK (lower(lender) <> lower(borrower)) NOT VALID;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_loans_status') THEN
        ALTER TABLE loans ADD CONSTRAINT ck_loans_status
            CHECK (status IN ('confirmed', 'partially_repaid', 'repaid',
                              'unpaid', 'refunded', 'disputed')) NOT VALID;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_lr_status') THEN
        ALTER TABLE loan_requests ADD CONSTRAINT ck_lr_status
            CHECK (request_status IN ('open', 'funded', 'expired', 'cancelled',
                                      'removed', 'duplicate', 'funded_backfill')) NOT VALID;
    END IF;
END
$$;

-- --------------------------------------------------------------------------
-- reddit_actions: retry bookkeeping for the sync worker (Phase 5)
-- --------------------------------------------------------------------------

ALTER TABLE reddit_actions
    ADD COLUMN IF NOT EXISTS attempts        INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS last_error      TEXT;

CREATE INDEX IF NOT EXISTS idx_reddit_actions_due
    ON reddit_actions (status, next_attempt_at)
    WHERE status = 'queued';
