-- Migration 019: Legacy Lender, a role an admin grants by hand (founders)
--
-- Separate from the earned tiers (tiers.py): shown alongside a lender's tier,
-- and it takes priority in their flair ("Verified Lender · Legacy").
--
-- Additive: new columns only.

ALTER TABLE user_roles
    ADD COLUMN IF NOT EXISTS legacy_lender     BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS legacy_granted_by TEXT,
    ADD COLUMN IF NOT EXISTS legacy_granted_at TIMESTAMP;
