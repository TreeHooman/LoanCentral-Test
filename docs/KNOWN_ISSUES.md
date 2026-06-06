# Known Issues

Use this file to track bot problems as we find them.

## Issue Template

```text
Title:
Command:
Expected:
Actual:
Example command/comment:
Log lines:
Production or test:
Status:
```

## Current Issues

### `$paid_with_id` sometimes cannot find a loan or says the lender is not authorized

Command: `$paid_with_id`

Expected: The recorded lender can mark a loan partially or fully paid using the loan ID shown by the bot.

Actual: Sometimes the bot says it cannot find the loan or the user does not have authority.

Likely areas:

- Loan ID confusion between internal `id` and stored `loan_id`.
- Lender username mismatch.
- Loan created under unexpected lender/borrower.
- Command using an ID from the wrong message.

Status: Partially fixed in upgrade branch. `$paid_with_id`, `$repaid`, and `$unpaid` now support internal database IDs and stored public loan IDs.

### `$stats` uses deprecated UTC datetime helpers on Python 3.14

Command: `$stats`

Expected: Tests and runtime should not emit datetime deprecation warnings.

Actual: Offline tests pass, but Python 3.14 warns about `datetime.utcnow()` and `datetime.utcfromtimestamp()`.

Likely areas:

- `commands/stats_command.py`

Status: Fixed in upgrade branch.

### `$confirm` blocks legitimate second loans between the same lender and borrower

Command: `$confirm`

Expected: A duplicate confirmation for the same loan should be blocked, but a new loan between the same lender and borrower should be allowed when it is on a different thread or has different loan details.

Actual: The old logic blocked any second confirmed loan between the same lender and borrower.

Status: Fixed in upgrade branch. Duplicate checks now include lender, borrower, amount, currency, original thread, and confirmed status.

### Repayment and status commands can drift stats in edge cases

Commands: `$paid_with_id`, `$repaid`, `$unpaid`, `$refunded`

Expected: Commands should not overpay loans, mark repaid/refunded loans unpaid, or reverse refund statistics more than once.

Actual: Old logic allowed over-recording repayment amounts, marking fully repaid loans unpaid, and processing an already refunded loan again.

Status: Fixed in upgrade branch. Overpayments are rejected, repaid/refunded loans cannot be marked unpaid, and already refunded loans do not reverse stats again.

### Payments on unpaid loans leave borrower unpaid totals wrong

Commands: `$paid_with_id`, `$repaid`

Expected: Payments on an unpaid loan should reduce `unpaid_amount` by the payment amount. When the loan becomes fully repaid, exactly one unpaid loan should be cleared.

Actual: Old logic did not reduce unpaid amount for partial payments and subtracted the original loan amount on full repayment, which could affect unrelated unpaid totals.

Status: Fixed in upgrade branch.
