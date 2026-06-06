import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from integrity import find_integrity_issues  # noqa: E402


def get_connection():
    load_dotenv(ROOT / ".env")
    host = os.getenv("DB_HOST", "localhost")
    ssl_mode = "require" if any(name in host for name in ("render.com", "amazonaws.com", "heroku.com")) else "prefer"
    return psycopg2.connect(
        host=host,
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        sslmode=ssl_mode,
    )


def fetch_rows():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, loan_id, lender, borrower, amount, currency, status, amount_repaid, original_thread
                FROM loans
                ORDER BY id
                """
            )
            loans = [
                {
                    "id": row[0],
                    "loan_id": row[1],
                    "lender": row[2],
                    "borrower": row[3],
                    "amount": row[4],
                    "currency": row[5],
                    "status": row[6],
                    "amount_repaid": row[7],
                    "original_thread": row[8],
                }
                for row in cur.fetchall()
            ]

            cur.execute(
                """
                SELECT username, loans_as_borrower, loans_as_lender, amount_borrowed,
                       amount_lent, amount_repaid, unpaid_loans, unpaid_amount
                FROM users
                ORDER BY username
                """
            )
            users = {
                row[0]: {
                    "loans_as_borrower": row[1],
                    "loans_as_lender": row[2],
                    "amount_borrowed": row[3],
                    "amount_lent": row[4],
                    "amount_repaid": row[5],
                    "unpaid_loans": row[6],
                    "unpaid_amount": row[7],
                }
                for row in cur.fetchall()
            }

        return loans, users
    finally:
        conn.close()


def main():
    loans, users = fetch_rows()
    issues = find_integrity_issues(loans, users)

    print(f"Checked {len(loans)} loans and {len(users)} users.")
    if not issues:
        print("No integrity issues found.")
        return 0

    print(f"Found {len(issues)} integrity issue(s):")
    for issue in issues:
        print(f"- {issue}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
