# Request-Funding Flow — Authorization & Audit-Log Review

**Date:** 2026-09-08
**Scope:** Uncommitted working-tree diff introducing the Reddit-request → dashboard → loan funding flow.
**Files:** `services.py`, `api/app.py`, `commands/fund_command.py`, `main.py`, `bot_messages.py`, `api/templates/*`, new `tests/test_request_funding_flow.py`.
**Verdict:** PASS. No security or correctness blockers found. Standing security rules honored. 620/620 tests green (was 606; +14 for this feature).

## What the feature does
A `[REQ]` post creates a `loan_requests` row and the bot reply now includes a `/record-request/<id>` dashboard deep-link. A verified lender funds it either via the dashboard (`POST /api/requests/<id>/fund`) or the `$fund` Reddit command. Funding creates the live loan, marks the request `funded`, updates lender stats, and writes an audit event — all in one transaction.

## Standing security rules — checked
- **Authorization enforced at two layers.** Route: `fund_request` / `create_loan_manual` now require `role in (lender, admin)`, a real session username, and `_is_lender_verified_fresh(lender)` → 403 otherwise. Service: `fund_loan_request` independently re-checks `get_verified_lender_status`. Defense in depth.
- **Impersonation closed.** Old code let the caller pass `lender` in the JSON body (`data.get("lender", session[...])`). Now a body `lender` that differs from the session user is rejected 403. Verified by `test_borrower_unverified_and_impersonation_rejected`.
- **DB is source of truth.** `create_loan(request_id=…)` re-reads borrower/amount/currency/method/thread from the locked `loan_requests` row and ignores caller-supplied values. Reddit input is not trusted for money fields.
- **Money action is audit-logged atomically.** `request_funded` is INSERTed into `audit_events` inside the same transaction as the loan + stats + status flip. `test_failed_audit_rolls_back_funding` proves that if the audit write fails, the whole funding rolls back — no silent unlogged mutation.
- **Input validation.** Repay amount/date validated (`Decimal.is_finite()`, positive, `date.fromisoformat`); NaN/Infinity/negative/list/bool/bad-date all rejected 400 with the request left `open` (`test_invalid_terms_leave_request_open`).
- **Parameterized queries.** All SQL in the diff uses `%s` bound params; no string-formatted SQL introduced.
- **Concurrency / double-spend.** Row is claimed via a locking `UPDATE … WHERE request_status='open' RETURNING`; a SAVEPOINT handles loan-id-collision retries without losing the lock. `test_two_concurrent_funders_create_only_one_loan` confirms exactly one loan under a 2-thread race.

## Follow-ups to confirm (not blockers)
1. **Route namespace vs table (CLAUDE.md trap).** `POST /api/requests/<id>/fund` lives under the OLD `/api/requests/*` namespace but operates on the NEW `loan_requests` table. The route path is unchanged by this diff (pre-existing), but CLAUDE.md says never mix the two. Confirm this bridge is intentional or move it to `/api/loan-requests/`.
2. **Admin now needs verified-lender to create loans.** `create_loan_manual` previously enforced the verified check only for `role == "lender"`; it now applies to admins too. Confirm this is intended (money action requires verification regardless of role) and not a repeat of the earlier admin-lockout class (commit e7929ae). Tests cover borrower→403 but not admin.
3. **Audit trail spans two tables.** `request_funded` goes to `audit_events` (raw INSERT, in-txn) while the follow-on `log_event("loan_created", …)` targets the `log_event` table. Both `audit_events` and `audit_logs` exist. Confirm dashboards/queries read the intended table.
4. **`notes` column overloaded** with `key:value;` pairs for currency/method/expires (`_request_metadata`). Works and is tested, but a malformed note silently falls back to defaults (USD, no method, no expiry). Candidate for real columns post-launch.

## Note
This review is code + offline tests only. It could not be validated against prod — the Render Postgres instance is dead (see MEMORY / DB status). The feature runs fully against SQLite dev/tests.
