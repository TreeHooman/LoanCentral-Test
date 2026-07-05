# Schema Parity Report — Sprint 6
Date: 2026-06-09

## Method
- Dev SQLite is generated directly from `schema.sql` by `local_db.py` (`_ensure_schema` runs the translated schema plus `_ensure_column` migrations), so dev parity with `schema.sql` holds by construction.
- Prod PostgreSQL (Render) was inspected read-only via `information_schema.columns` and `pg_indexes`.

## Column parity — PASS
All required fields exist in prod:

| Field | Table | Status |
|---|---|---|
| verified_lender / verified_lender_at / verified_lender_by | user_roles | ✓ |
| reddit_username (+ linked_at / linked_by) | user_roles | ✓ |
| perm_version | user_roles | ✓ |
| notifications table | — | ✓ |
| verification_applications table | — | ✓ |
| audit_logs table | — | ✓ |
| audit_events table | — | ✓ |
| loan_events table | — | ✓ |
| interest_amount / interest_rate / payment_timing | loans | ✓ |

## SQLite-only differences (expected, by design)
- `SERIAL PRIMARY KEY` → `INTEGER PRIMARY KEY AUTOINCREMENT`
- `JSONB` → `TEXT`
- `NOW()` → `CURRENT_TIMESTAMP`
- `verified_lender BOOLEAN` → `INTEGER` (0/1)
These are handled by `local_db._translate_sql` and do not affect behavior.

## PostgreSQL-only tables (expected)
- `lender_keys`, `borrower_otp_sessions`, `borrower_magic_links` — created by service code on first use; also created in SQLite the same way.

## Indexes — FIXED
Prod was missing 23 indexes declared in `schema.sql` (only the `loans` indexes and `idx_user_roles_role` existed — prod also had extra composite loan indexes `idx_loans_lender_status`, `idx_loans_borrower_status`, `idx_loans_status_date`, which were kept).

### Applied to prod 2026-06-09 (all `CREATE INDEX IF NOT EXISTS`, additive)
- user_roles: `idx_user_roles_reddit_username`, `idx_user_roles_verified_lender` (new in Sprint 6)
- loan_attachments: `idx_attachments_loan_id`
- loan_requests: `idx_loan_requests_status`, `idx_loan_requests_borrower`, `idx_loan_requests_request_id`
- audit_events: `idx_audit_events_created_at`, `idx_audit_events_type`, `idx_audit_events_actor`, `idx_audit_events_target_user`
- verification_applications: `idx_verification_status`, `idx_verification_username`
- reddit_actions: `idx_reddit_actions_status`, `idx_reddit_actions_type`, `idx_reddit_actions_target`
- audit_logs: `idx_audit_logs_actor`, `idx_audit_logs_action`, `idx_audit_logs_created`, `idx_audit_logs_target` (target composite new in Sprint 6)
- loan_events: `idx_loan_events_loan_id`, `idx_loan_events_created`
- notifications: `idx_notifications_username`, `idx_notifications_unread`

`schema.sql` was updated with the three new Sprint 6 indexes so fresh installs match prod.

## Recommendations
- Run `schema.sql` against prod after any new table/index is added (it is fully idempotent).
- Re-check parity before each deploy (see BACKUP_RESTORE.md checklist).
