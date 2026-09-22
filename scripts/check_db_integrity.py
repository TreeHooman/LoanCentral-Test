"""
Report rows that violate LoanCentral's data invariants.

Read-only — this script never writes, updates, or deletes anything.

Run it before applying migration 013's constraints to a database that has been
collecting data (the live one, whenever bot 2.0 is reconnected). Migration 013
adds its CHECK constraints NOT VALID, so they bind new writes without rejecting
existing rows; this tells you what would have to be cleaned up before those
constraints can be VALIDATEd.

Usage:
    python scripts/check_db_integrity.py
    python scripts/check_db_integrity.py --verbose   # list offending rows
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LOAN_STATUSES = ("confirmed", "partially_repaid", "repaid",
                 "unpaid", "refunded", "disputed")
REQUEST_STATUSES = ("open", "funded", "expired", "cancelled",
                    "removed", "duplicate", "funded_backfill")


def _in_list(values):
    return "(" + ", ".join(["%s"] * len(values)) + ")"


# (label, sql, params, why_it_matters)
CHECKS = [
    (
        "loan_requests sharing one Reddit post",
        """SELECT reddit_post_id, COUNT(*) FROM loan_requests
           WHERE reddit_post_id IS NOT NULL
           GROUP BY reddit_post_id HAVING COUNT(*) > 1""",
        (),
        "blocks uq_lr_reddit_post_id; duplicate imports of the same [REQ] post",
    ),
    (
        "loan_requests sharing one funded loan",
        """SELECT funded_loan_id, COUNT(*) FROM loan_requests
           WHERE funded_loan_id IS NOT NULL
           GROUP BY funded_loan_id HAVING COUNT(*) > 1""",
        (),
        "blocks uq_lr_funded_loan_id; two requests claiming one loan",
    ),
    (
        "loans sharing one public loan_id",
        """SELECT loan_id, COUNT(*) FROM loans
           WHERE loan_id IS NOT NULL
           GROUP BY loan_id HAVING COUNT(*) > 1""",
        (),
        "blocks uq_loans_loan_id; $paid_with_id would act on the wrong loan",
    ),
    (
        "loans with a non-positive amount",
        "SELECT id, loan_id, amount FROM loans WHERE amount <= 0",
        (),
        "blocks ck_loans_amount_positive",
    ),
    (
        "loans with negative amount_repaid",
        "SELECT id, loan_id, amount_repaid FROM loans WHERE amount_repaid < 0",
        (),
        "blocks ck_loans_repaid_non_negative",
    ),
    (
        "loans where lender and borrower are the same person",
        "SELECT id, loan_id, lender FROM loans WHERE lower(lender) = lower(borrower)",
        (),
        "blocks ck_loans_parties_differ",
    ),
    (
        "loans with an unrecognised status",
        f"SELECT id, loan_id, status FROM loans WHERE status NOT IN {_in_list(LOAN_STATUSES)}",
        LOAN_STATUSES,
        "blocks ck_loans_status",
    ),
    (
        "loan_requests with an unrecognised status",
        f"""SELECT request_id, request_status FROM loan_requests
            WHERE request_status NOT IN {_in_list(REQUEST_STATUSES)}""",
        REQUEST_STATUSES,
        "blocks ck_lr_status",
    ),
    # --- consistency problems the brief asks about (no constraint, but real) ---
    (
        "requests marked funded with no linked loan",
        """SELECT request_id, request_status FROM loan_requests
           WHERE request_status = 'funded' AND funded_loan_id IS NULL""",
        (),
        "request review shows these as funded but there is no loan record",
    ),
    (
        "requests linked to a loan that no longer exists",
        """SELECT r.request_id, r.funded_loan_id FROM loan_requests r
           LEFT JOIN loans l ON l.id = r.funded_loan_id
           WHERE r.funded_loan_id IS NOT NULL AND l.id IS NULL""",
        (),
        "dangling link; the loan detail page will 404",
    ),
    (
        "open requests that already passed their due date",
        """SELECT request_id, requested_due_date FROM loan_requests
           WHERE request_status = 'open' AND requested_due_date IS NOT NULL
             AND requested_due_date < CURRENT_DATE""",
        (),
        "stale open requests; expire_old_requests has not run",
    ),
]


def main():
    load_dotenv(ROOT / ".env")
    verbose = "--verbose" in sys.argv

    from utils import get_db_connection
    conn = get_db_connection()
    if not conn:
        print("Database connection failed.")
        return 1

    is_sqlite = getattr(conn, "is_sqlite", False)
    backend = "SQLite" if is_sqlite else "PostgreSQL"
    if is_sqlite:
        target = os.getenv("SQLITE_DB_PATH") or "data/loancentral_dev.sqlite3"
    else:
        target = os.getenv("DB_NAME") or "(from DATABASE_URL)"
    print(f"Integrity check — {backend} — {target}\n")

    problems = 0
    skipped = 0
    try:
        for label, sql, params, why in CHECKS:
            cur = conn.cursor()
            try:
                cur.execute(sql, params)
                rows = cur.fetchall() or []
            except Exception as exc:
                # A missing table/column is information, not a crash.
                conn.rollback()
                print(f"  ?  {label}: could not check ({exc})")
                skipped += 1
                continue
            finally:
                cur.close()

            if rows:
                problems += 1
                print(f"  X  {label}: {len(rows)}")
                print(f"       {why}")
                if verbose:
                    for row in rows[:20]:
                        print(f"       {row}")
                    if len(rows) > 20:
                        print(f"       ... and {len(rows) - 20} more")
            else:
                print(f"  OK {label}")

        print()
        if problems:
            print(f"{problems} problem group(s) found. Re-run with --verbose to list rows.")
            print("Nothing was changed — fix these before VALIDATEing the constraints.")
        else:
            print("No violations found.")
        if skipped:
            print(f"{skipped} check(s) skipped (table or column not present).")
        return 1 if problems else 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
