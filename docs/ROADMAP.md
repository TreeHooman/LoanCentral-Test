# LoanCentral Upgrade Roadmap

## Goal

Ship a tested LoanCentral bot upgrade within 40 active work hours without touching live Reddit accounts or the production database during development.

## Safety Rules

- Do not run the bot against production Reddit credentials during development.
- Do not run tests against the production database.
- Keep real `.env` files out of Git.
- Test command logic offline before using any Reddit API.
- Use a test Reddit account and test subreddit only after offline tests pass.
- Keep rollback possible before production integration.

## Milestones

### 1. Protected Baseline

Status: Done

- Git repo initialized.
- Current bot committed as baseline.
- Upgrade branch created.
- Safe env templates added.

### 2. Offline Test Harness

Status: Started

- Add fake Reddit comment, author, submission, subreddit, and reply objects.
- Allow command handlers to be tested without Reddit API calls.
- Capture bot replies in memory.

Current coverage:

- `$paid_with_id` lookup, authorization, currency mismatch, partial payment, and full payment.
- `$confirm` loan creation, requester authorization, duplicate prevention, and lender format parsing.
- `$repaid`, `$unpaid`, `$refunded`, `$health`, and `$help` starter offline regression coverage.
- `$loan`, `$stats`, and `$mods` starter offline regression coverage.

### 3. Test Database Path

Status: Pending

- Use a dedicated test database only.
- Add reset/setup helpers for test data.
- Keep production database untouched.

### 4. Command Regression Tests

Status: Pending

Test these flows:

- `$loan`
- `$confirm`
- `$paid_with_id`
- `$repaid`
- `$unpaid`
- `$refunded`
- `$stats`
- `$health`
- `$help`

### 5. Core Fixes

Status: Pending

- Standardize which loan ID users should enter.
- Fix loan lookup and authorization errors.
- Fix repayment, unpaid, and refund status transitions.
- Fix user statistics drift.
- Improve error messages.

### 6. Integrity Checks

Status: Pending

- Detect mismatched user totals.
- Detect overpaid loans.
- Detect bad loan statuses.
- Detect missing user records.
- Detect duplicate or suspicious active loans.

### 7. Test Reddit Staging

Status: Pending

- Use only test credentials.
- Use only a test/private subreddit.
- Confirm Reddit replies, flair checks, and command parsing.

### 8. Production Integration

Status: Pending

- Backup production database.
- Stop old bot.
- Run integrity checks.
- Deploy tested code.
- Run one controlled live flow.
- Monitor logs.
- Keep rollback ready.
