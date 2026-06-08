"""
Seed realistic demo data for dashboard testing.
Creates: users, loans (various statuses), loan requests.
Run: python scripts/seed_demo.py
Safe to re-run — skips anything already inserted.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(".env.test", override=True)
os.environ["LOANCENTRAL_ENV"] = "dev"
os.environ.setdefault("DB_BACKEND", "sqlite")

from datetime import datetime, timedelta, date
from decimal import Decimal
from services import _get_db

now = datetime.now

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

USERS = [
    # (username, loans_as_borrower, loans_as_lender, amount_borrowed, amount_lent, amount_repaid, unpaid_loans, unpaid_amount)
    ("testlender",        0, 12, 0,       3450.00, 0,       0, 0),
    ("testmod",           0,  2, 0,        400.00, 0,       0, 0),
    ("testborrower",      4,  0, 625.00,   0,      510.00,  0, 0),
    ("remote_weather186", 3,  0, 420.00,   0,      350.00,  0, 0),
    ("thomasmcthumb",     5,  0, 830.00,   0,      680.00,  1, 150.00),
    ("jennelleisiam",     2,  0, 350.00,   0,      350.00,  0, 0),
    ("quickloan_user",    6,  0, 1200.00,  0,      900.00,  1, 200.00),
    ("newbie_borrower",   1,  0, 100.00,   0,        0,     0, 0),
    ("reliable_rick",     8,  0, 1600.00,  0,     1600.00,  0, 0),
    ("ghost_user99",      2,  0, 280.00,   0,        0,     2, 280.00),
    ("lender_pro",        0,  8, 0,       2100.00,   0,     0, 0),
    ("sarah_borrows",     3,  0, 450.00,   0,      300.00,  0, 0),
]

LOANS = [
    # (lender, borrower, amount, currency, status, amount_repaid, days_ago, thread)
    # --- testlender's active loans ---
    ("testlender", "testborrower",      150.00, "USD", "confirmed",        0,      5,  "https://reddit.com/r/borrow/comments/abc001"),
    ("testlender", "remote_weather186", 200.00, "USD", "confirmed",        0,      3,  "https://reddit.com/r/borrow/comments/abc002"),
    ("testlender", "newbie_borrower",   100.00, "USD", "confirmed",        0,      1,  "https://reddit.com/r/borrow/comments/abc003"),
    # --- testlender's partial ---
    ("testlender", "sarah_borrows",     250.00, "USD", "partially_repaid", 100.00, 12, "https://reddit.com/r/borrow/comments/abc004"),
    ("testlender", "thomasmcthumb",     120.00, "USD", "partially_repaid", 70.00,  8,  "https://reddit.com/r/borrow/comments/abc005"),
    # --- testlender's repaid ---
    ("testlender", "jennelleisiam",     200.00, "USD", "repaid",           200.00, 30, "https://reddit.com/r/borrow/comments/abc006"),
    ("testlender", "reliable_rick",     300.00, "USD", "repaid",           300.00, 45, "https://reddit.com/r/borrow/comments/abc007"),
    ("testlender", "reliable_rick",     200.00, "USD", "repaid",           200.00, 60, "https://reddit.com/r/borrow/comments/abc008"),
    ("testlender", "testborrower",       75.00, "USD", "repaid",            75.00, 20, "https://reddit.com/r/borrow/comments/abc009"),
    # --- testlender's unpaid (in mod review queue) ---
    ("testlender", "ghost_user99",      150.00, "USD", "unpaid",           0,      25, "https://reddit.com/r/borrow/comments/abc010"),
    ("testlender", "quickloan_user",    200.00, "USD", "unpaid",           0,      18, "https://reddit.com/r/borrow/comments/abc011"),
    # --- testlender's refunded ---
    ("testlender", "thomasmcthumb",      50.00, "USD", "refunded",         0,      40, "https://reddit.com/r/borrow/comments/abc012"),
    # --- lender_pro loans ---
    ("lender_pro", "quickloan_user",    300.00, "USD", "confirmed",        0,      2,  "https://reddit.com/r/borrow/comments/abc013"),
    ("lender_pro", "sarah_borrows",     200.00, "USD", "partially_repaid", 200.00, 15, "https://reddit.com/r/borrow/comments/abc014"),
    ("lender_pro", "reliable_rick",     500.00, "USD", "repaid",           500.00, 90, "https://reddit.com/r/borrow/comments/abc015"),
    ("lender_pro", "ghost_user99",      130.00, "USD", "unpaid",           0,      35, "https://reddit.com/r/borrow/comments/abc016"),
    # --- testmod loans ---
    ("testmod",    "remote_weather186", 150.00, "USD", "repaid",           150.00, 50, "https://reddit.com/r/borrow/comments/abc017"),
    ("testmod",    "sarah_borrows",     250.00, "USD", "confirmed",        0,      4,  "https://reddit.com/r/borrow/comments/abc018"),
]

REQUESTS = [
    # (request_id, borrower, amount, currency, repay_amount, repay_days, payment_method, post_hours_ago, thread)
    ("REQ-0001", "remote_weather186", 150.00, "USD", 200.00, 12,  "PayPal",  4,   "https://reddit.com/r/borrow/comments/req001"),
    ("REQ-0002", "thomasmcthumb",     150.00, "USD", 210.00, 6,   None,      16,  "https://reddit.com/r/borrow/comments/req002"),
    ("REQ-0003", "jennelleisiam",     200.00, "USD", None,   10,  "PayPal",  96,  "https://reddit.com/r/borrow/comments/req003"),  # repay_amount blank — mandatory fill
    ("REQ-0004", "newbie_borrower",    75.00, "USD",  90.00, 14,  "Venmo",   2,   "https://reddit.com/r/borrow/comments/req004"),
    ("REQ-0005", "quickloan_user",    500.00, "USD", 550.00, 30,  "Zelle",   1,   "https://reddit.com/r/borrow/comments/req005"),
    ("REQ-0006", "sarah_borrows",     100.00, "USD", 120.00, 7,   "CashApp", 6,   "https://reddit.com/r/borrow/comments/req006"),
    ("REQ-0007", "reliable_rick",     250.00, "USD", 275.00, 21,  "PayPal",  0.5, "https://reddit.com/r/borrow/comments/req007"),
    ("REQ-0008", "remote_weather186",  80.00, "USD", 100.00, 9,   "PayPal",  3,   "https://reddit.com/r/borrow/comments/req008"),
]

ROLES = [
    ("testadmin",         "admin"),
    ("testmod",           "mod"),
    ("testlender",        "lender"),
    ("testborrower",      "borrower"),
    ("lender_pro",        "lender"),
    ("remote_weather186", "borrower"),
    ("thomasmcthumb",     "borrower"),
    ("jennelleisiam",     "borrower"),
    ("quickloan_user",    "borrower"),
    ("newbie_borrower",   "borrower"),
    ("reliable_rick",     "borrower"),
    ("ghost_user99",      "borrower"),
    ("sarah_borrows",     "borrower"),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run():
    conn = _get_db()
    if not conn:
        print("ERROR: Could not connect to database.")
        sys.exit(1)

    cur = conn.cursor()

    # Ensure loan_requests table exists
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
    conn.commit()

    # ---- Users ----
    u_ins = 0
    for (username, loans_b, loans_l, amt_b, amt_l, amt_r, unpaid, unpaid_amt) in USERS:
        cur.execute("SELECT 1 FROM users WHERE username = %s", (username,))
        if cur.fetchone():
            continue
        cur.execute("""
            INSERT INTO users (username, loans_as_borrower, loans_as_lender, amount_borrowed,
                               amount_lent, amount_repaid, unpaid_loans, unpaid_amount, last_updated)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (username, loans_b, loans_l, amt_b, amt_l, amt_r, unpaid, unpaid_amt, now()))
        u_ins += 1

    # ---- Roles ----
    r_ins = 0
    for (username, role) in ROLES:
        cur.execute("SELECT 1 FROM user_roles WHERE username = %s", (username,))
        if cur.fetchone():
            continue
        cur.execute("""
            INSERT INTO user_roles (username, role, subscription_status, last_login)
            VALUES (%s, %s, 'free', %s)
        """, (username, role, now() - timedelta(hours=1)))
        r_ins += 1

    # ---- Loans ----
    import time as _time
    l_ins = 0
    for (lender, borrower, amount, currency, status, repaid, days_ago, thread) in LOANS:
        cur.execute("SELECT 1 FROM loans WHERE original_thread = %s", (thread,))
        if cur.fetchone():
            continue
        loan_id  = str(int(_time.time() * 1000) % 1000000000 + l_ins)
        created  = now() - timedelta(days=days_ago)
        updated  = created + timedelta(days=1) if status != "confirmed" else created
        payment_method = {
            "remote_weather186": "PayPal",
            "thomasmcthumb": "Cash App",
            "jennelleisiam": "Venmo",
            "quickloan_user": "Zelle",
            "sarah_borrows": "PayPal",
            "newbie_borrower": "Venmo",
        }.get(borrower, "PayPal")
        due_offsets = {
            "abc001": -1,
            "abc002": 0,
            "abc003": 2,
            "abc004": 3,
            "abc005": 9,
            "abc010": -8,
            "abc011": -3,
            "abc013": 4,
            "abc018": 1,
        }
        thread_key = thread.rsplit("/", 1)[-1]
        repay_date = (date.today() + timedelta(days=due_offsets[thread_key])) if thread_key in due_offsets else None
        repay_amount = round(float(amount) * 1.12, 2) if status in ("confirmed", "partially_repaid", "unpaid") else amount
        cur.execute("""
            INSERT INTO loans (loan_id, lender, borrower, amount, currency,
                               date_created, original_thread, status, amount_repaid, last_updated,
                               repay_amount, repay_date, payment_method)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (loan_id, lender, borrower, amount, currency, created, thread, status, repaid, updated,
              repay_amount, repay_date, payment_method))
        l_ins += 1

    # ---- Requests ----
    req_ins = 0
    for (req_id, borrower, amount, currency, repay_amt, repay_days, pay_method, hrs_ago, thread) in REQUESTS:
        cur.execute("SELECT 1 FROM loan_requests WHERE request_id = %s", (req_id,))
        if cur.fetchone():
            continue
        post_date  = now() - timedelta(hours=hrs_ago)
        repay_date = (date.today() + timedelta(days=repay_days)) if repay_days else None
        cur.execute("""
            INSERT INTO loan_requests
            (request_id, borrower, amount, currency, repay_amount, repay_date,
             payment_method, post_date, thread_link, status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'open')
        """, (req_id, borrower, amount, currency, repay_amt, repay_date, pay_method, post_date, thread))
        req_ins += 1

    conn.commit()
    cur.close()
    conn.close()

    print(f"Done.")
    print(f"  Users inserted:    {u_ins}")
    print(f"  Roles inserted:    {r_ins}")
    print(f"  Loans inserted:    {l_ins}")
    print(f"  Requests inserted: {req_ins}")


if __name__ == "__main__":
    run()
