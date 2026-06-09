"""
fix_lender_typos.py — one-time data correction for lender username typos.

These loans were created during a historical data import where lender names
were typed manually instead of being read from the Reddit API, introducing
small typos. This script renames them to the canonical (correct) username.

Run ONCE on prod after verifying the mappings below are correct:
    python scripts/fix_lender_typos.py --dry-run   # preview only
    python scripts/fix_lender_typos.py              # apply changes

Safe to re-run — uses ON CONFLICT / exact match so duplicates are skipped.
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from services import _get_db

# -----------------------------------------------------------------------
# KNOWN TYPO → CORRECT MAPPINGS
# Determined by edit-distance analysis of all lender names + cross-ref
# with original Reddit threads.
# -----------------------------------------------------------------------
CORRECTIONS = {
    # typo stored in DB            → canonical Reddit username
    "embarassed-throat42":         "embarrassed-throat42",      # missing 'r'
    "embarrassedthroat-42":        "embarrassed-throat42",      # hyphen moved

    "entreneurprior334":           "entrepreneurprior334",      # missing 'repre'
    "entrpeneurprior334":          "entrepreneurprior334",
    "entrepreneurpior334":         "entrepreneurprior334",      # missing 'r'
    "entrepreneurprior335":        "entrepreneurprior334",      # digit off
    "entrepreneurpriot334":        "entrepreneurprior334",      # 'r' → 't'
    "entreprenuerprior334":        "entrepreneurprior334",      # transposed letters
}


def apply_corrections(dry_run=True):
    conn = _get_db()
    if not conn:
        print("ERROR: Could not connect to database.")
        sys.exit(1)

    cur = conn.cursor()
    total_updated = 0

    for typo, correct in CORRECTIONS.items():
        # Count affected rows
        cur.execute("SELECT COUNT(*) FROM loans WHERE lower(lender) = lower(%s)", (typo,))
        count = cur.fetchone()[0]
        if count == 0:
            print(f"  SKIP  {typo!r} -> {correct!r}  (0 rows)")
            continue

        print(f"  {'WOULD FIX' if dry_run else 'FIXING'}  {typo!r} -> {correct!r}  ({count} loan{'s' if count != 1 else ''})")

        if not dry_run:
            # Rename lender column
            cur.execute(
                "UPDATE loans SET lender = %s WHERE lower(lender) = lower(%s)",
                (correct, typo)
            )
            lender_rows = cur.rowcount

            # Rename borrower column (in case a typo user ever borrowed too)
            cur.execute(
                "UPDATE loans SET borrower = %s WHERE lower(borrower) = lower(%s)",
                (correct, typo)
            )
            borrower_rows = cur.rowcount

            # Fix users table
            cur.execute("SELECT 1 FROM users WHERE lower(username) = lower(%s)", (typo,))
            if cur.fetchone():
                # If the correct username already exists, merge stats then delete typo row
                cur.execute("SELECT 1 FROM users WHERE lower(username) = lower(%s)", (correct,))
                if cur.fetchone():
                    # Merge: add typo stats into correct row, then delete typo
                    cur.execute("""
                        UPDATE users SET
                            loans_as_lender  = users.loans_as_lender  + t.loans_as_lender,
                            loans_as_borrower= users.loans_as_borrower+ t.loans_as_borrower,
                            amount_lent      = users.amount_lent      + t.amount_lent,
                            amount_borrowed  = users.amount_borrowed  + t.amount_borrowed,
                            amount_repaid    = users.amount_repaid    + t.amount_repaid,
                            unpaid_loans     = users.unpaid_loans     + t.unpaid_loans,
                            unpaid_amount    = users.unpaid_amount    + t.unpaid_amount
                        FROM users t
                        WHERE lower(users.username) = lower(%s)
                          AND lower(t.username) = lower(%s)
                    """, (correct, typo))
                    cur.execute("DELETE FROM users WHERE lower(username) = lower(%s)", (typo,))
                else:
                    # No correct row yet — just rename
                    cur.execute(
                        "UPDATE users SET username = %s WHERE lower(username) = lower(%s)",
                        (correct, typo)
                    )

            # Fix user_roles table
            cur.execute("SELECT 1 FROM user_roles WHERE lower(username) = lower(%s)", (typo,))
            if cur.fetchone():
                cur.execute("SELECT 1 FROM user_roles WHERE lower(username) = lower(%s)", (correct,))
                if cur.fetchone():
                    # Correct row already exists — just delete the typo row
                    cur.execute("DELETE FROM user_roles WHERE lower(username) = lower(%s)", (typo,))
                else:
                    cur.execute(
                        "UPDATE user_roles SET username = %s WHERE lower(username) = lower(%s)",
                        (correct, typo)
                    )

            total_updated += lender_rows
            print(f"         updated {lender_rows} lender + {borrower_rows} borrower rows in loans")

    if dry_run:
        print("\n[DRY RUN] No changes written. Run without --dry-run to apply.")
        conn.rollback()
    else:
        conn.commit()
        print(f"\nDone. {total_updated} total loan rows corrected.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fix typo lender usernames in the loans table.")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without applying them")
    args = parser.parse_args()
    apply_corrections(dry_run=args.dry_run)
