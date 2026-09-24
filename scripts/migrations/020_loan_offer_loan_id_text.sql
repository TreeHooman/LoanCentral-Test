-- Migration 020: loan_offers.loan_db_id holds the loan's public ID
--
-- create_loan returns the public loan ID (e.g. "1790292191862"), which is
-- text and larger than INTEGER. Storing it here failed on Postgres after the
-- loan was saved, so `$confirm` recorded the loan but never replied.
--
-- Widens the column (existing values are kept, as text). Guarded, so running
-- it twice is a no-op.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'loan_offers' AND column_name = 'loan_db_id' AND data_type <> 'text'
    ) THEN
        ALTER TABLE loan_offers ALTER COLUMN loan_db_id TYPE TEXT USING loan_db_id::TEXT;
    END IF;
END $$;
