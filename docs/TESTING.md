# Testing Guide

## Current Safety Level

The current tests are offline tests. They do not connect to Reddit, do not use Reddit API credentials, and do not connect to the production database.

The tests replace `utils.get_db_connection` with fake in-memory objects and capture bot replies locally.

## Run Offline Tests

From the project folder:

```powershell
python -m unittest discover -s tests
```

If Python is not installed or not on PATH, install Python first or rebuild the project virtual environment.

## Do Not Use Yet

Do not run these against:

- the production Reddit bot account
- production Reddit credentials
- the production database
- live subreddit streams

## First Regression Coverage

The first tests cover `$paid_with_id`:

- lender can record partial payment by database ID
- lender can record full payment by public loan ID
- wrong lender gets a clear authorization error
- missing loan gets a clear not-found error
- currency mismatch does not update the loan
- payment larger than the remaining balance is rejected
- payments on unpaid loans reduce unpaid amount correctly
- zero-value payments and payments on refunded loans are rejected

The `$confirm` tests cover:

- original requester can confirm a loan
- zero-value confirmations are rejected
- `/u/name` and `u/name` lender formats work
- non-original requester cannot confirm
- exact duplicate confirmation is blocked
- same lender and borrower can confirm a different thread

Additional offline command coverage:

- `$loan` verified lender flow, unverified lender block, self-loan silence, and zero-value rejection
- `$stats` fake Reddit history reporting, empty history reply, and missing-username silence
- `$mods` fake modmail capture, user reply, and non-command silence
- `$repaid` borrower authorization and partial repayment
- `$unpaid` lender authorization and remaining-balance unpaid tracking
- `$repaid` and `$unpaid` support both internal database IDs and stored public loan IDs
- `$repaid` rejects payments larger than the remaining balance
- `$repaid` payments on unpaid loans reduce unpaid amount correctly
- `$repaid` rejects zero-value payments and refunded loans
- `$unpaid` rejects already repaid loans
- `$refunded` lender authorization, refund status, stat reversal, and moderator notification capture
- `$refunded` does not reverse stats again when a loan is already refunded
- `$health` no-history and borrower total reporting
- `$help` core command listing and non-command silence
