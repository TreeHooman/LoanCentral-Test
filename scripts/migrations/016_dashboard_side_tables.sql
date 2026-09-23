-- Migration 016: dashboard tables that only schema.sql created
--
-- Found moving the dashboard to Neon: after a restore plus 001-015, these four
-- tables were still missing. They exist on a database only once the bot has
-- started (main.init_database runs schema.sql). The dashboard never does that,
-- so until the bot had run against the same database, analytics writes were
-- silently dropped and feedback, announcements and notification settings
-- failed.
--
-- Definitions match schema.sql. Additive: IF NOT EXISTS throughout, so this is
-- a no-op on a database the bot has already initialised.

CREATE TABLE IF NOT EXISTS analytics_events (
    id SERIAL PRIMARY KEY,
    username TEXT,
    event_type TEXT NOT NULL,
    page TEXT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_analytics_event_type ON analytics_events(event_type);
CREATE INDEX IF NOT EXISTS idx_analytics_created_at ON analytics_events(created_at);

CREATE TABLE IF NOT EXISTS announcements (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    author TEXT NOT NULL,
    pinned BOOLEAN NOT NULL DEFAULT FALSE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_announcements_active ON announcements(active);
CREATE INDEX IF NOT EXISTS idx_announcements_created ON announcements(created_at);

CREATE TABLE IF NOT EXISTS feedback_submissions (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    reviewed_by TEXT,
    reviewer_note TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_feedback_username ON feedback_submissions(username);
CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback_submissions(status);
CREATE INDEX IF NOT EXISTS idx_feedback_category ON feedback_submissions(category);

CREATE TABLE IF NOT EXISTS notification_preferences (
    username TEXT PRIMARY KEY,
    due_date_reminders BOOLEAN NOT NULL DEFAULT TRUE,
    status_updates BOOLEAN NOT NULL DEFAULT TRUE,
    verification_updates BOOLEAN NOT NULL DEFAULT TRUE,
    dispute_updates BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMP DEFAULT NOW()
);
