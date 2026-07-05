# DATA_MODEL.md

Postgres in prod, SQLite in dev/tests. Base schema in `schema.sql`; runtime
`_ensure_*` helpers in `services.py` create/migrate some tables beyond it.

> ⚠️ `schema.sql` is **stale for `loan_requests`** — the live table (created by
> `_ensure_loan_requests_table`) uses `borrower_username`, `requested_amount`,
> `request_status`, `thread_url`, `funded_loan_id`, `reddit_username`; the
> migration `migrations/migrate_loan_requests.py` renamed the old columns on
> prod. Trust `services.py`, not `schema.sql`, for this table.

## Core tables

### loans — one row per recorded loan
- Identity: `id` (serial) + `loan_id` (public text ID); lookups accept either.
- Parties: `lender`, `borrower` (Reddit usernames, matched case-insensitively).
- Money: `amount`, `repay_amount` (defaults to amount), `amount_repaid`,
  `currency`, optional `interest_amount`/`interest_rate`.
- `status` lifecycle: `confirmed → partially_repaid → repaid`, or
  `unpaid` (default flagged by lender), `refunded`, `disputed`.
- Borrower acknowledgement: `borrower_acknowledged_at/_note`.
- `payment_timing`: `early` / `late` / `on_time` / NULL.

**Invariants** (enforced in `services.py`, not DB constraints):
- Only the loan's recorded lender may run lender actions on it; only its
  borrower may run borrower actions (case-insensitive match).
- Repayments: total capped at 1.5× `repay_amount`; overpayment beyond the
  remaining balance is recorded as exact settlement.
- `repaid`/`refunded` loans reject further payments; currency must match.
- Every state change writes `loan_events` + audit rows in the same transaction.

### users — aggregate stats cache (per username)
Recomputed from loan rows (`loans_as_lender`, `amount_lent`, `unpaid_loans`,
…). A cache, not a source of truth — safe to recompute.

### user_roles — **the** permission source of truth
- `role`: `borrower` (default) / `lender` / `mod` / `admin`.
- `verified_lender` + `verified_lender_at/_by` — gates lender bot commands and
  the lender dashboard. Reddit flair is never read to grant anything.
- `perm_version` — bumped on permission changes; sessions re-check the DB when
  it differs (bounds session-cache staleness).
- Borrower contact (`contact_email`/`contact_phone`) for OTP login;
  `reddit_username` link fields.

### loan_requests — [REQ] posts (NEW system)
Live columns per `_ensure_loan_requests_table`. `request_id` like `REQ-0042`;
`request_status`: `open, funded, expired, cancelled, removed, duplicate,
funded_backfill` (`_LR_STATUSES`); `funded_loan_id` → `loans.loan_id`.
Companion `request_events` table = immutable per-request timeline.
**Do not confuse with the OLD `/api/requests/*` system** (deprecated).

## Audit / activity tables (all append-only)

| Table | What it records |
|---|---|
| `audit_events` | bot + system events (JSONB details) |
| `audit_logs` | dashboard mod/admin actions (old/new value JSON, IP) |
| `loan_events` | per-loan timeline shown on loan detail |
| `request_events` | per-request timeline |
| `analytics_events` | page views, searches (operational analytics) |

Rule: anything that moves money or reputation writes an audit row in the same
transaction (docs/SECURITY.md rule 6).

## Supporting tables

- `verification_applications` — lender verification queue (pending/approved/denied).
- `reddit_actions` — staged outbound Reddit writes (`queued → sent/skipped/failed/cancelled`); the only path to live Reddit mutations.
- `notifications` / `notification_preferences` — in-app notifications + opt-outs.
- `feedback_submissions` — user bug reports/suggestions.
- `announcements` — platform notices (public GET serves `active_only`).
- `loan_attachments` — dashboard file uploads, keyed by `loan_id`.

## Conventions

- Usernames stored lowercase-ish but **always compare with `lower()`**.
- Public IDs are text (`loan_id`, `request_id`); serial `id` is internal.
  Lookup queries accept either (`WHERE id::text = %s OR loan_id = %s`).
- All queries parameterized — no string-built SQL (docs/SECURITY.md rule 5).
- Indexes: see `schema.sql` + `idx_lr_*` created in `_ensure_loan_requests_table`.
