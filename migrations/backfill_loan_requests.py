"""
backfill_loan_requests.py

Create funded_backfill loan request records for existing loans that have no
linked request. Safe to run multiple times — never overwrites existing records.

Usage:
    python backfill_loan_requests.py            # dry run
    python backfill_loan_requests.py --commit   # write to database
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services import backfill_requests_from_loans

dry_run = "--commit" not in sys.argv

print("=" * 60)
print("Loan Request Backfill Tool")
print("=" * 60)
if dry_run:
    print("DRY RUN — no changes will be written. Pass --commit to apply.\n")
else:
    print("LIVE RUN — changes will be written to the database.\n")

created, skipped, error = backfill_requests_from_loans(dry_run=dry_run)

if error:
    print(f"ERROR: {error}")
    sys.exit(1)

label = "Would create" if dry_run else "Created"
print(f"{label}: {created} request record(s)")
print(f"Skipped:  {skipped} loan(s) (missing borrower or insert error)")

if dry_run and created:
    print("\nRe-run with --commit to apply these changes.")
elif not dry_run and created:
    print("\nBackfill complete. Records have status 'funded_backfill'.")
else:
    print("\nNothing to backfill — all loans are already linked to requests.")
