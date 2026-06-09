-- Migration 010: Notification framework
CREATE TABLE IF NOT EXISTS notifications (
    id                  SERIAL PRIMARY KEY,
    username            TEXT NOT NULL,
    notification_type   TEXT NOT NULL,
    title               TEXT NOT NULL,
    message             TEXT NOT NULL,
    read                BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notif_username ON notifications (lower(username));
CREATE INDEX IF NOT EXISTS idx_notif_unread   ON notifications (lower(username), read) WHERE read = FALSE;
CREATE INDEX IF NOT EXISTS idx_notif_created  ON notifications (created_at DESC);
