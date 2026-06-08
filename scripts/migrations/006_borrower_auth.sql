-- Migration 006: Borrower contact info + OTP sessions
ALTER TABLE user_roles
    ADD COLUMN IF NOT EXISTS contact_email TEXT,
    ADD COLUMN IF NOT EXISTS contact_phone TEXT;

CREATE TABLE IF NOT EXISTS borrower_otp_sessions (
    id           SERIAL PRIMARY KEY,
    username     TEXT        NOT NULL,
    otp_hash     TEXT        NOT NULL,
    contact      TEXT        NOT NULL,
    contact_type TEXT        NOT NULL CHECK (contact_type IN ('email','sms')),
    expires_at   TIMESTAMP   NOT NULL,
    used         BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMP   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_otp_username ON borrower_otp_sessions (username, used, expires_at);
