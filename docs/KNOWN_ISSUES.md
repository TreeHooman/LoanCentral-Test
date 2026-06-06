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

Status: Needs offline regression test before final fix.

### `$stats` uses deprecated UTC datetime helpers on Python 3.14

Command: `$stats`

Expected: Tests and runtime should not emit datetime deprecation warnings.

Actual: Offline tests pass, but Python 3.14 warns about `datetime.utcnow()` and `datetime.utcfromtimestamp()`.

Likely areas:

- `commands/stats_command.py`

Status: Needs cleanup during fix pass.
