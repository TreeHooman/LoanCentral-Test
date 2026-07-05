# LoanCentral — Private Beta Readiness Checklist
Date: 2026-06-09 | Sprint 3

Use this checklist before opening LoanCentral to the first real users.
Each item must be checked off, not just read.

---

## 1. Security & Auth

- [ ] `IS_DEV` / `LOANCENTRAL_ENV` is set to `"prod"` on the production server. Dev-login routes (`/auth/dev-login`, `/auth/dev-login-as/<username>`) must be unreachable.
- [ ] Verify `SECRET_KEY` is a strong random value (not the dev default) in production environment variables.
- [ ] Confirm no credentials, API keys, or `SECRET_KEY` values are committed to the repository (check `.env`, `config.py`, etc.).
- [ ] `X-API-Key` header auth is disabled or scoped to lender-only routes in production (review `require_auth` vs `login_required` on sensitive endpoints).
- [ ] Rate limiting or brute-force protection on `/api/auth/borrower/claim` and `/api/auth/borrower/verify` (OTP steps).
- [ ] Review all `role_required` and `require_mod_api` decorators for any recently-added routes not yet in `security_audit.md`.

---

## 2. Database

- [ ] PostgreSQL production database is running with latest schema applied (including `perm_version`, `reddit_username` columns).
- [ ] All `_ensure_column` migrations in `local_db.py` are reflected in the production schema — run a schema diff if uncertain.
- [ ] Database backups are scheduled and verified restorable.
- [ ] Indexes exist on high-traffic columns: `loans(lender)`, `loans(borrower)`, `loans(status)`, `user_roles(role)`.
- [ ] No raw `SQLITE_DB_PATH` or local SQLite paths reachable in production.

---

## 3. Reddit Bot

- [ ] Bot Reddit credentials (`CLIENT_ID`, `CLIENT_SECRET`, `REDDIT_USERNAME`, `REDDIT_PASSWORD`) are set in production env — not committed to source.
- [ ] Bot is processing the correct subreddit (not a test sub).
- [ ] Bot replies are going out with production-correct language (check `REPLY_*` strings in `loan_command.py` et al.).
- [ ] "Do not trust Reddit flair for permissions" constraint remains in place — database is still sole source of truth for `verified_lender`.
- [ ] Reddit API rate limiter (`reddit_limiter`) is configured appropriately for production traffic.

---

## 4. Dashboard Access

- [ ] At least one admin account is set up in `user_roles`.
- [ ] At least one mod account is set up for day-to-day moderation.
- [ ] Lender verification workflow is tested end-to-end: application → mod review → grant/revoke → dashboard access changes immediately via `perm_version`.
- [ ] Borrower OTP login tested with a real email or SMS (if SMS configured).
- [ ] Magic link (`/view/<token>`) confirmed working, tokens expire after configured duration.

---

## 5. Features Confirmed Working

- [ ] Loan creation from dashboard (lender) — requires verified lender; fresh DB check.
- [ ] Loan creation from Reddit bot (`$loan` command) — requires DB-verified lender.
- [ ] Mark paid / unpaid / refunded from dashboard.
- [ ] Bulk-paid from dashboard.
- [ ] Dispute flow (borrower submits → mod can see).
- [ ] Audit log viewer (`/dashboard/admin/audit-log`) — filters work.
- [ ] Global search (`/dashboard/admin/search`) — results link to correct pages.
- [ ] Notification bell — unread count updates on new notification.
- [ ] Loan timeline modal — events load, `escapeHtml` prevents XSS.
- [ ] Per-loan calendar ICS (`/api/loans/<id>/calendar.ics`) — valid ICS, scope-checked.
- [ ] Reddit username linking (mod → roles tab → 🔗 Reddit button) — link/unlink, audit logged.
- [ ] Borrower calendar (`/view/<token>/calendar.ics`) — magic-link-gated.

---

## 6. Content & Language

- [ ] All user-facing messages reviewed against `language_audit.md`. Confirm "Verified Lender" language is neutral and non-misleading.
- [ ] Terms of service page (`/terms`) is up to date.
- [ ] Error messages do not leak internal stack traces to non-admin users.
- [ ] No placeholder text (e.g., "Lorem ipsum", "TODO", "FIXME") visible to end users.

---

## 7. Monitoring & Ops

- [ ] Application error logging is configured (e.g., Sentry, server-side log file) and alert goes to a monitored inbox.
- [ ] Health check endpoint exists (or a simple `GET /` returning 200 when logged in).
- [ ] Deployment checklist reviewed — `pip install -r requirements.txt` is up to date.
- [ ] `IS_DEV=False` confirmed in production WSGI/gunicorn environment (do not rely on default).

---

## 8. Deferred (not required for private beta)

| Item | Reason Deferred |
|------|-----------------|
| Reddit OAuth login | Deferred until after dashboard complete (see `memory/project_auth_future.md`) |
| Lender API key management UI | Endpoint exists; no self-service UI yet |
| Interest display on dashboard | Fields stored but not prominently displayed |
| Attachment upload size cap | Type-check exists; no server-side size enforcement |
| Mobile dashboard polish | Works on desktop; mobile layout untested |
