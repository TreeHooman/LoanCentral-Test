"""
Seed example loan requests into the database for dashboard testing.
Run: python scripts/seed_requests.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(".env.dev")

from datetime import datetime, timedelta
from services import _get_db

REQUESTS = [
    {
        "request_id":     "REQ-0001",
        "borrower":       "remote_weather186",
        "amount":         150.00,
        "currency":       "USD",
        "repay_amount":   200.00,
        "repay_date":     (datetime.now() + timedelta(days=12)).date(),
        "payment_method": "PayPal",
        "post_date":      datetime.now() - timedelta(hours=4),
        "thread_link":    "https://reddit.com/r/borrow/comments/example1",
        "reddit_post_id": "example1",
        "status":         "open",
    },
    {
        "request_id":     "REQ-0002",
        "borrower":       "thomasmcthumberstein",
        "amount":         150.00,
        "currency":       "USD",
        "repay_amount":   210.00,
        "repay_date":     (datetime.now() + timedelta(days=6)).date(),
        "payment_method": None,
        "post_date":      datetime.now() - timedelta(hours=16),
        "thread_link":    "https://reddit.com/r/borrow/comments/example2",
        "reddit_post_id": "example2",
        "status":         "open",
    },
    {
        "request_id":     "REQ-0003",
        "borrower":       "jennelleisiam",
        "amount":         200.00,
        "currency":       "USD",
        "repay_amount":   None,  # not stated — lender must fill in
        "repay_date":     (datetime.now() + timedelta(days=10)).date(),
        "payment_method": "PayPal",
        "post_date":      datetime.now() - timedelta(days=4),
        "thread_link":    "https://reddit.com/r/borrow/comments/example3",
        "reddit_post_id": "example3",
        "status":         "open",
    },
    {
        "request_id":     "REQ-0004",
        "borrower":       "testborrower",
        "amount":         75.00,
        "currency":       "USD",
        "repay_amount":   90.00,
        "repay_date":     (datetime.now() + timedelta(days=14)).date(),
        "payment_method": "Venmo",
        "post_date":      datetime.now() - timedelta(hours=2),
        "thread_link":    "https://reddit.com/r/borrow/comments/example4",
        "reddit_post_id": "example4",
        "status":         "open",
    },
    {
        "request_id":     "REQ-0005",
        "borrower":       "quickloan_user",
        "amount":         500.00,
        "currency":       "USD",
        "repay_amount":   550.00,
        "repay_date":     (datetime.now() + timedelta(days=30)).date(),
        "payment_method": "Zelle",
        "post_date":      datetime.now() - timedelta(hours=1),
        "thread_link":    "https://reddit.com/r/borrow/comments/example5",
        "reddit_post_id": "example5",
        "status":         "open",
    },
]

def run():
    conn = _get_db()
    if not conn:
        print("ERROR: Could not connect to database.")
        sys.exit(1)

    cur = conn.cursor()

    # Create table if missing
    cur.execute("""
        CREATE TABLE IF NOT EXISTS loan_requests (
            id SERIAL PRIMARY KEY,
            request_id TEXT UNIQUE NOT NULL,
            borrower TEXT NOT NULL,
            amount NUMERIC NOT NULL,
            currency TEXT NOT NULL DEFAULT 'USD',
            repay_amount NUMERIC,
            repay_date DATE,
            payment_method TEXT,
            post_date TIMESTAMP NOT NULL,
            thread_link TEXT NOT NULL,
            reddit_post_id TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            funded_by TEXT,
            funded_date TIMESTAMP,
            loan_id TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    inserted = 0
    skipped  = 0
    for r in REQUESTS:
        cur.execute("SELECT 1 FROM loan_requests WHERE request_id = %s", (r["request_id"],))
        if cur.fetchone():
            skipped += 1
            continue
        cur.execute("""
            INSERT INTO loan_requests
            (request_id, borrower, amount, currency, repay_amount, repay_date,
             payment_method, post_date, thread_link, reddit_post_id, status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            r["request_id"], r["borrower"], r["amount"], r["currency"],
            r["repay_amount"], r["repay_date"], r["payment_method"],
            r["post_date"], r["thread_link"], r["reddit_post_id"], r["status"]
        ))
        inserted += 1

    conn.commit()
    cur.close()
    conn.close()
    print(f"Done — {inserted} requests inserted, {skipped} already existed.")

if __name__ == "__main__":
    run()
