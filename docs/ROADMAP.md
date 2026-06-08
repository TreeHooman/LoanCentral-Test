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

Status: Done

- Add fake Reddit comment, author, submission, subreddit, and reply objects.
- Allow command handlers to be tested without Reddit API calls.
- Capture bot replies in memory.

Current coverage:

- `$paid_with_id` lookup, authorization, currency mismatch, partial payment, and full payment.
- `$confirm` loan creation, requester authorization, duplicate prevention, and lender format parsing.
- `$repaid`, `$unpaid`, `$refunded`, `$health`, and `$help` starter offline regression coverage.
- `$loan`, `$stats`, and `$mods` starter offline regression coverage.

### 3. Test Database Path

Status: Done

- Use a dedicated test database only.
- Add reset/setup helpers for test data.
- Keep production database untouched.

### 4. Command Regression Tests

Status: Done

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

Status: Done

- Standardize which loan ID users should enter.
- Fix loan lookup and authorization errors.
- Fix repayment, unpaid, and refund status transitions.
- Fix user statistics drift.
- Improve error messages.

### 6. Integrity Checks

Status: Done

- Detect mismatched user totals.
- Detect overpaid loans.
- Detect bad loan statuses.
- Detect missing user records.
- Detect duplicate or suspicious active loans.

Current coverage:

- Pure offline integrity checker can report invalid loan states and user aggregate mismatches.
- Read-only database integrity runner added for dev/staging database checks.
- Test database schema setup script added with test-database safety guard.

### 6b. Service Layer

Status: Done

- All business logic extracted from command files into services.py.
- Commands now only handle Reddit parsing and replies.
- main.py generate_user_info uses get_user_profile() from services.
- services.py functions: create_loan(), mark_repaid(), mark_unpaid(), mark_refunded(), get_user_profile().
- Ready for future API/dashboard to call the same functions.

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

## Dashboard / Platform Backlog

### Borrower And Lender Dashboard

Status: In progress

- Done: borrower profile page from clickable usernames, scoped to own/mod/shared-loan visibility.
- Done: CSV loan export for borrower and lender history.
- Done: lender loan search by borrower name, loan ID, status, and notes.
- Done: overdue loans are highlighted in red on borrower/lender tables.
- Done: lender due-soon alert panel highlights overdue and next-due loans.
- Done: days since funded column on active loan tables.
- Done: sortable lender and borrower loan tables.
- Done: lender dashboard defaults to most-relevant sorting with next due/overdue loans first.
- Done: lender can edit repay amount and due date on open loans.
- Done: lender can bulk mark selected active loans fully paid.
- Done: copy loan summary button for lender records.
- Done: mobile dashboard polish for lender/borrower views with card-style loan rows, tap-friendly controls, and no horizontal overflow at phone widths.
- Done: borrower can see agreed payment method/contact info for each loan when recorded.
- Done: borrower can acknowledge a loan as received from the dashboard, with timestamp, optional note, audit event, API field, and CSV export.
- Pending: borrower profile shows account age and Reddit join date once OAuth/API support is enabled.

### Mod Dashboard

Status: In progress

- Done: backend live activity feed API for recent audit events.
- Pending: visible activity tab polish in the mod dashboard.
- Private mod notes on borrowers.
- Ban log with issuer, confirmation status, reason, and timestamp.
- Manual loan status override with audit reason.
- Delete fraudulent or erroneous loan records with audit trail.
- Community stats: total volume, repayment rate, unpaid rate over time.
- Filter unpaid loans by lender.
- Reassign loan from one lender to another for edge cases.
- Add notes to unpaid review queue decisions.
- Search all users across the platform.

### Loan Request System

Status: In progress

- Done: request auto-expiry service and mod API trigger.
- Done: open request listing auto-runs expiry checks when enabled by config.
- Done: lender/mod private note API for a request before funding.
- Done: duplicate open request detection helper for the bot/mod layer.
- Done: lender can cancel/reject a specific looked-up REQ-ID from the Record Loan modal, with audit logging and without exposing a browsable request marketplace.
- Done: duplicate open request warning appears during specific REQ-ID lookup before funding.
- Pending: visible mod view for oldest open requests.

### Bot

Status: In progress

- Done: bot generates a REQ-ID in the same history reply when a `[REQ]` post is saved.
- Done: bot command cooldown to reduce spam and Reddit API pressure.
- Bot comments repayment reminders X days before due date.
- Bot comments when a dashboard loan is funded.
- Bot comments congratulations when a loan is fully repaid.
- `$extend` command for borrower due-date extension requests.
- Graceful handling for deleted or removed posts.
- Done: deleted/removed posts with no author are skipped gracefully.
- Done: timestamped audit log service for major bot/dashboard actions.
- Process manager setup so the bot restarts automatically after crashes.
- DM lender when borrower repay date passes with no repayment.

### Devvit Feasibility

Status: Researched

- Devvit can read/write Reddit content with Reddit's developer platform API client.
- Devvit can use app accounts, scheduler jobs, Redis-style storage, and moderator APIs.
- Good Devvit candidates: REQ-ID comments, simple moderation actions, scheduled reminders, lightweight post/comment handlers, mod-only utilities.
- Keep external Python/Postgres for now for full dashboard, relational loan history, exports, audit logs, verification records, and cross-view reporting.
- Possible hybrid: Devvit handles Reddit-native events and calls LoanCentral's backend API for the source-of-truth database.
- Avoid rebuilding the whole dashboard in Devvit until storage, reporting, and relational-query limits are fully proven.

### Auth And Roles

Status: Pending

- Reddit flair check on OAuth login to auto-assign lender role.
- One-click Reddit ban after mod confirmation.
- Lender verification application flow with mod approve/deny.
- Done: session expiry warning API and dashboard banner for sessions close to expiring.
- Revoke lender dashboard access without removing Reddit flair.

### Tech And Infrastructure

Status: In progress

- Done: migration script for dashboard columns and request tables.
- Done: move uploads folder outside `api/` by default so files survive code deploys.
- Done: dashboard/API rate limiting.
- Done: Flask API logging with user and timestamp.
- Done: deployment checklist draft.
- Done: audit/activity table for immutable trust events.
