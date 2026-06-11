"""
One-time migration: rename loan_requests columns from old bot schema to new dashboard schema.

Safe to run multiple times — each ALTER is skipped if the column already has the new name.

Old schema (from schema.sql / bot):
  borrower, amount, repay_amount, repay_date, status, thread_link

New schema (from _ensure_loan_requests_table / dashboard):
  borrower_username, requested_amount, requested_repayment_amount,
  requested_due_date, request_status, thread_url

Run on prod:
  python migrate_loan_requests.py
Or via psql (copy the SQL from MIGRATION_SQL below and paste into the Render psql console).
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

MIGRATION_SQL = """
DO $$
BEGIN
    -- borrower → borrower_username
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'loan_requests' AND column_name = 'borrower'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'loan_requests' AND column_name = 'borrower_username'
    ) THEN
        ALTER TABLE loan_requests RENAME COLUMN borrower TO borrower_username;
        RAISE NOTICE 'Renamed borrower -> borrower_username';
    ELSE
        RAISE NOTICE 'borrower_username already exists or borrower not found — skipping';
    END IF;

    -- amount → requested_amount
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'loan_requests' AND column_name = 'amount'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'loan_requests' AND column_name = 'requested_amount'
    ) THEN
        ALTER TABLE loan_requests RENAME COLUMN amount TO requested_amount;
        RAISE NOTICE 'Renamed amount -> requested_amount';
    ELSE
        RAISE NOTICE 'requested_amount already exists or amount not found — skipping';
    END IF;

    -- repay_amount → requested_repayment_amount
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'loan_requests' AND column_name = 'repay_amount'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'loan_requests' AND column_name = 'requested_repayment_amount'
    ) THEN
        ALTER TABLE loan_requests RENAME COLUMN repay_amount TO requested_repayment_amount;
        RAISE NOTICE 'Renamed repay_amount -> requested_repayment_amount';
    ELSE
        RAISE NOTICE 'requested_repayment_amount already exists or repay_amount not found — skipping';
    END IF;

    -- repay_date → requested_due_date
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'loan_requests' AND column_name = 'repay_date'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'loan_requests' AND column_name = 'requested_due_date'
    ) THEN
        ALTER TABLE loan_requests RENAME COLUMN repay_date TO requested_due_date;
        RAISE NOTICE 'Renamed repay_date -> requested_due_date';
    ELSE
        RAISE NOTICE 'requested_due_date already exists or repay_date not found — skipping';
    END IF;

    -- status → request_status
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'loan_requests' AND column_name = 'status'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'loan_requests' AND column_name = 'request_status'
    ) THEN
        ALTER TABLE loan_requests RENAME COLUMN status TO request_status;
        RAISE NOTICE 'Renamed status -> request_status';
    ELSE
        RAISE NOTICE 'request_status already exists or status not found — skipping';
    END IF;

    -- thread_link → thread_url
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'loan_requests' AND column_name = 'thread_link'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'loan_requests' AND column_name = 'thread_url'
    ) THEN
        ALTER TABLE loan_requests RENAME COLUMN thread_link TO thread_url;
        RAISE NOTICE 'Renamed thread_link -> thread_url';
    ELSE
        RAISE NOTICE 'thread_url already exists or thread_link not found — skipping';
    END IF;

    -- Add new columns if missing
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'loan_requests' AND column_name = 'reddit_username'
    ) THEN
        ALTER TABLE loan_requests ADD COLUMN reddit_username VARCHAR(100);
        RAISE NOTICE 'Added reddit_username';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'loan_requests' AND column_name = 'reddit_comment_id'
    ) THEN
        ALTER TABLE loan_requests ADD COLUMN reddit_comment_id VARCHAR(30);
        RAISE NOTICE 'Added reddit_comment_id';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'loan_requests' AND column_name = 'notes'
    ) THEN
        ALTER TABLE loan_requests ADD COLUMN notes TEXT;
        RAISE NOTICE 'Added notes';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'loan_requests' AND column_name = 'updated_at'
    ) THEN
        ALTER TABLE loan_requests ADD COLUMN updated_at TIMESTAMP NOT NULL DEFAULT NOW();
        RAISE NOTICE 'Added updated_at';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'loan_requests' AND column_name = 'funded_loan_id'
    ) THEN
        ALTER TABLE loan_requests ADD COLUMN funded_loan_id INTEGER REFERENCES loans(id) ON DELETE SET NULL;
        RAISE NOTICE 'Added funded_loan_id';
    END IF;

    -- Rebuild indexes with new column names (old ones become stale after rename)
    DROP INDEX IF EXISTS idx_loan_requests_status;
    DROP INDEX IF EXISTS idx_loan_requests_borrower;
    CREATE INDEX IF NOT EXISTS idx_lr_borrower ON loan_requests (lower(borrower_username));
    CREATE INDEX IF NOT EXISTS idx_lr_status   ON loan_requests (request_status);
    CREATE INDEX IF NOT EXISTS idx_lr_created  ON loan_requests (created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_lr_reddit   ON loan_requests (reddit_post_id) WHERE reddit_post_id IS NOT NULL;
    RAISE NOTICE 'Indexes rebuilt';

END $$;
"""


def run():
    try:
        import psycopg2
    except ImportError:
        sys.exit("psycopg2 not installed. Run: pip install psycopg2-binary")

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        host = os.getenv("DB_HOST")
        port = os.getenv("DB_PORT", "5432")
        name = os.getenv("DB_NAME")
        user = os.getenv("DB_USER")
        pw   = os.getenv("DB_PASSWORD")
        if host and name and user:
            db_url = f"postgresql://{user}:{pw}@{host}:{port}/{name}"
        else:
            sys.exit("Set DATABASE_URL or DB_HOST/DB_NAME/DB_USER/DB_PASSWORD in environment.")

    print("Connecting to database...")
    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    cur = conn.cursor()

    print("Running migration...")
    cur.execute(MIGRATION_SQL)
    conn.commit()
    print("Migration complete.")

    # Verify final column names
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'loan_requests'
        ORDER BY ordinal_position
    """)
    cols = [r[0] for r in cur.fetchall()]
    print(f"\nloan_requests columns after migration:\n  {', '.join(cols)}")

    required = {"borrower_username", "request_status", "thread_url",
                "requested_amount", "requested_repayment_amount", "requested_due_date"}
    missing = required - set(cols)
    if missing:
        print(f"\nWARNING: still missing columns: {missing}")
        sys.exit(1)
    else:
        print("\nAll required columns present. Migration successful.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    run()
