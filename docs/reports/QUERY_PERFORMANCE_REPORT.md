# Query Performance Report — Sprint 7
Date: 2026-06-09

## Method
Static analysis of `services.py` and `api/app.py` — every DB call traced through the five major dashboard load paths, with focus on N+1 patterns, redundant connections, and unbounded result sets.

## Findings by path

### Dashboard load (mod/admin)
`GET /dashboard/mod` and `GET /dashboard/admin` render the template only; all data is fetched client-side via separate API calls. No server-side N+1 risk at page load.

The mod dashboard JS fires these API calls on tab open:
- `/api/loans` — single query with status/search filters, LIMIT 200
- `/api/requests` — single query, LIMIT 100
- `/api/admin/roles` — single query returning all user_roles rows (unbounded — see below)
- `/api/reminders` — single query via `get_active_loans`
- `/api/admin/audit-log` — paginated (LIMIT 50)
- `/api/admin/integrity` — 6 separate single-table scans — **acceptable** (integrity checks are infrequent)

**Issue found:** `/api/admin/roles` (`list_roles`) returns ALL user_roles rows with no LIMIT/pagination. Fine at 12 users; becomes slow and expensive at scale.

**Fix applied:** Added limit/offset params with a 500-row default cap (see services.py `list_roles_paged` note — route-level fix below).

### User/lender profile
`get_user_profile`: 3 sequential queries (users table, active loan count, user_roles). Acceptable — no N+1.
`get_admin_user_profile`: 5 sequential queries (identity, lender loan stats, borrower loan stats, outstanding, loan events, audit logs, verifications). All single-pass aggregates — no N+1.

### Global search
`global_search`: up to 3 sequential queries (loans, users, verifications). Each is independently bounded by LIMIT param. No N+1.

### Notification center
`get_notifications`: 3 sequential queries (unread count, total count, paginated rows). Fine post-Sprint 7 pagination fix.

### Lender directory
`list_lenders`: single compound query with LEFT JOIN aggregate sub-query. PostgreSQL will use `idx_loans_lender` for the sub-query aggregate. No N+1.

### Audit log viewer
`get_audit_log`: 2 queries (COUNT then paginated SELECT). Both use `WHERE` clauses indexed by `idx_audit_logs_actor`, `idx_audit_logs_action`, `idx_audit_logs_created`, `idx_audit_logs_target`.

## Issues found and fixed

### 1. `/api/admin/roles` — unbounded query
**Before:** `SELECT * FROM user_roles ORDER BY role, username` — no LIMIT.
**Fix:** Added `limit` and `offset` params to the route (default 500 cap).

### 2. Redundant DB connections in `_get_all_loans_from_db`
The `_get_all_loans_from_db` helper in `api/app.py` opens its own DB connection independently of the calling route. This creates two open connections for routes that also call services. Acceptable at current scale; noted for future consolidation.

### 3. `get_active_loans` — no LIMIT
`get_active_loans(username)` in services.py has no row cap. For a single user this is not a problem, but for the reminder queue (which iterates ALL active loans across all users) the query is unbounded. At beta scale this is fine; worth adding a safety cap at 1,000+ loans.

## Applied fix — roles API pagination

```python
# api/app.py — list_roles
limit  = min(int(request.args.get("limit", 500)), 1000)
offset = int(request.args.get("offset", 0))
# ... WHERE clause unchanged ...
ORDER BY role, username LIMIT %s OFFSET %s
```
