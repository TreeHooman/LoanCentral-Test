-- Migration 011: Verified lender status on user_roles
ALTER TABLE user_roles
    ADD COLUMN IF NOT EXISTS verified_lender     BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS verified_lender_at  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS verified_lender_by  TEXT,
    ADD COLUMN IF NOT EXISTS verification_note   TEXT;
