# Index Audit Report — Sprint 7
Date: 2026-06-09

## Method
Indexes verified against live prod PostgreSQL (Render, Oregon) and schema.sql.
Sprint 6 already applied 23 indexes. This report is the comprehensive final audit.

## Current index inventory (prod)

| Table | Index | Columns | Purpose |
|---|---|---|---|
| audit_events | idx_audit_events_actor | actor | Filter by acting user |
| audit_events | idx_audit_events_created_at | created_at | Time-range queries |
| audit_events | idx_audit_events_target_user | target_user | Target lookups |
| audit_events | idx_audit_events_type | event_type | Filter by event type |
| audit_logs | idx_audit_logs_action | action_type | Filter by action |
| audit_logs | idx_audit_logs_actor | actor_username | Filter by actor |
| audit_logs | idx_audit_logs_created | created_at | Time-range queries |
| audit_logs | idx_audit_logs_target | (target_type, target_id) | Composite target lookups |
| loan_attachments | idx_attachments_loan_id | loan_id | Attachment lookup by loan |
| loan_events | idx_loan_events_created | created_at | Timeline ordering |
| loan_events | idx_loan_events_loan_id | loan_id | Timeline by loan |
| loan_requests | idx_loan_requests_borrower | borrower | Requests by borrower |
| loan_requests | idx_loan_requests_request_id | request_id | Direct lookup |
| loan_requests | idx_loan_requests_status | status | Filter open/funded/expired |
| loans | idx_loans_borrower | borrower | Borrower loan list |
| loans | idx_loans_borrower_status | (borrower, status) | Filtered borrower view |
| loans | idx_loans_date_created | date_created | Timeline ordering |
| loans | idx_loans_lender | lender | Lender loan list |
| loans | idx_loans_lender_status | (lender, status) | Filtered lender view |
| loans | idx_loans_status | status | Global status filter |
| loans | idx_loans_status_date | (status, date_created) | Status + time sort |
| notifications | idx_notifications_unread | (username, read) | Unread count + bell badge |
| notifications | idx_notifications_username | username | All notifications for user |
| reddit_actions | idx_reddit_actions_status | status | Queue management |
| reddit_actions | idx_reddit_actions_target | target_user | By target user |
| reddit_actions | idx_reddit_actions_type | action_type | Filter by type |
| user_roles | idx_user_roles_reddit_username | reddit_username | Reddit link lookups |
| user_roles | idx_user_roles_role | role | Filter by role |
| user_roles | idx_user_roles_verified_lender | verified_lender | VL directory filter |
| verification_applications | idx_verification_status | status | Queue by status |
| verification_applications | idx_verification_username | username | Lookup by user |

All primary key indexes (`*_pkey`) and unique constraints (`*_key`, `loan_id_key`, etc.) also exist.

## Missing indexes assessed

| Table | Column(s) | Verdict | Rationale |
|---|---|---|---|
| users | username | PK already; no secondary needed | Primary key IS the index |
| user_roles | username | PK already | Primary key |
| loans | loan_id | Unique constraint index already exists | `loans_loan_id_key` |
| audit_logs | (target_type, target_id) | ✓ Already exists | `idx_audit_logs_target` (Sprint 6) |
| notifications | (username, read) | ✓ Already exists | `idx_notifications_unread` |

No missing indexes found. All recommended indexes from Tasks 1 and 8 of the sprint brief are present.

## Performance rationale for key indexes

**loans composite indexes** (`idx_loans_lender_status`, `idx_loans_borrower_status`, `idx_loans_status_date`): These cover the most frequent dashboard queries — lender dashboard filters by (lender, status), borrower dashboard filters by (borrower, status), and mod dashboard filters by (status, date_created). Postgres can satisfy these queries with index-only scans.

**notifications composite** (`idx_notifications_unread`): The notification bell fetches unread count on every page load. With `(username, read)`, the count query avoids a full table scan.

**audit_logs target composite** (`idx_audit_logs_target`): Admin lender profile loads recent audit logs for a user or loan. `(target_type, target_id)` is more selective than either column alone.

**user_roles** (`idx_user_roles_verified_lender`, `idx_user_roles_reddit_username`): Admin lender directory filters on both columns; partial filters on boolean `verified_lender` are cheap with this index even for low-cardinality columns.

## Recommendations
- No new indexes needed at current scale (7 loans, 12 users).
- Re-run this audit at 1,000 loans — the composite loan indexes may benefit from more selective prefixes at scale.
- Consider a partial index on `loans(status)` WHERE `status IN ('confirmed','partially_repaid')` if active-loan queries dominate at scale.
- Monitor slow query log in Render after beta launch.
