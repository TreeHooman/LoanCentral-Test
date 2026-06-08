-- Migration 004: interest tracking
-- Stores the agreed interest on a loan as recorded from post text or manual entry.
-- LoanCentral never sets or suggests a rate — it only records what was agreed.

ALTER TABLE loans
    ADD COLUMN IF NOT EXISTS interest_amount NUMERIC,   -- dollar value e.g. 30.00
    ADD COLUMN IF NOT EXISTS interest_rate   NUMERIC;   -- percentage e.g. 25.00 (means 25%)
