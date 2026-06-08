CREATE TABLE IF NOT EXISTS verification_applications (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL,
    requested_role TEXT NOT NULL DEFAULT 'lender',
    status TEXT NOT NULL DEFAULT 'pending',
    public_note TEXT,
    private_note TEXT,
    reviewer TEXT,
    review_note TEXT,
    submitted_at TIMESTAMP DEFAULT NOW(),
    reviewed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_verification_status ON verification_applications(status);
CREATE INDEX IF NOT EXISTS idx_verification_username ON verification_applications(username);
