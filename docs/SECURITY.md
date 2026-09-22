# SECURITY.md — Standing security rules

Evergreen rules for LoanCentral. These are constraints, not suggestions — any
change (human or AI) that violates one needs explicit sign-off from the owner
first. See also `docs/reports/security_audit.md` and
`docs/reports/PERMISSION_AUDIT_REPORT.md` for point-in-time audit results.

## The 10 rules

### 1. No Reddit OAuth
Do not implement Reddit OAuth for dashboard login. Auth is deferred by design
(lender API keys + borrower OTP); OAuth is revisited only after the dashboard
is complete, as an explicit decision.

### 2. The database is the source of truth for permissions — never Reddit flair
Roles (`users.role`: borrower/lender/mod/admin) and verified-lender status live
in the DB. Reddit flair is display-only and user-influencable; never read it to
grant permissions.

Because the bot sees a Reddit handle and the DB is keyed on the dashboard
username, resolve identity through `services.resolve_user_identity` rather than
comparing names directly — a raw comparison silently denies linked accounts.
The optional flair gate (`REQUIRE_LENDER_FLAIR`) may only ever restrict, never
grant, and must fail open when the flair cannot be read.

### 3. No production-credential changes without permission
`.env` points at the live Render Postgres. Never rotate, edit, or copy prod
credentials (DB, `API_KEY`, `SECRET_KEY`, Reddit creds) without the owner's
explicit go-ahead.

### 4. No live Reddit API writes unless explicitly marked safe
Bot replies, bans, flair changes etc. must go through the `reddit_actions`
queue (`enqueue_reddit_action`) for human review — never call the live Reddit
API directly from new code unless the task is explicitly marked safe for live
calls. Dev/test uses stubs.

### 5. Parameterized queries only
All SQL goes through placeholders (`%s` / `?` via `local_db.py`). Never build
SQL with f-strings, `+`, or `.format()` on user-supplied values — including
usernames from Reddit.

### 6. Audit-log every money action
Any action that creates or mutates a loan, repayment, refund, dispute, or ban
must write an audit/event record in the same transaction (see
`_log_request_event_with_cursor` pattern). If it moves money or reputation, it
leaves a trail.

### 7. All bot input is untrusted
Reddit comments, usernames, amounts, and URLs are attacker-controlled.
Validate types/ranges, normalize usernames, escape anything rendered into
templates or bot replies. A `$` command is an unauthenticated API call.

### 8. No secrets in code or logs
Secrets live in `.env` / Render env vars only. Never commit them, never log
them, never put API keys in URLs — keys are **header-only** (`X-API-Key`);
the query-string fallback was deliberately removed. Don't reintroduce it.

### 9. Permission checks belong in a decorator or a shared helper
Every write route must carry a recognised gate. Inline, copy-pasted checks are
how `/api/loans/<id>/dispute` shipped without one — it trusted a username from
the request body and wrote the audit row against the victim. Use
`_lender_write_actor()`, the `require_*` decorators, or `role_required`.
`tests/test_permissions_realdb.py::EveryWriteRouteHasAGateTests` fails the
build if a new write route has none; fix the route, don't widen the exemptions.

### 10. Security-relevant tests must hit a real database
A `MagicMock` connection accepts SQL no database would, so a mocked test
proves nothing about permissions, constraints or transactions. Anything
covering auth, loan state or migrations uses
`tests/support/dbcase.RealDBTestCase`.

## Enforcement conventions

- Dashboard pages: `@role_required("mod", "admin")` (or stricter).
- JSON API: `@require_auth` (session or `X-API-Key`), `@require_mod_api`,
  `@require_admin_api`.
- List endpoints must scope results to the caller unless mod/admin — the
  `/api/loans` leak (fixed 2026-06-25, commit `7ae6c3c`) is the cautionary tale.
- Never take an acting username from the request body. Bind it to the session
  and, where linked accounts matter, widen with `account_aliases()` — never
  with whatever the browser sent.
- Bans are global and checked centrally (`reject_banned_users`); they resolve
  through `account_aliases`, so a banned user cannot switch to their other
  name.
