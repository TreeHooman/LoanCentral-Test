CREATE TABLE IF NOT EXISTS reddit_actions (
    id SERIAL PRIMARY KEY,
    action_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    target_user TEXT,
    loan_id TEXT,
    request_id TEXT,
    subreddit TEXT,
    payload JSONB,
    reason TEXT,
    created_by TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_reddit_actions_status ON reddit_actions(status);
CREATE INDEX IF NOT EXISTS idx_reddit_actions_type ON reddit_actions(action_type);
CREATE INDEX IF NOT EXISTS idx_reddit_actions_target ON reddit_actions(target_user);
