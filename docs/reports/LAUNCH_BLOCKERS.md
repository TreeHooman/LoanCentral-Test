# Launch Blockers — Sprint 7
Date: 2026-06-09

## Summary
No critical blockers remain after Sprints 6 and 7. All high-priority hardening tasks are complete. Items below are ranked by launch risk.

---

## Critical — Must fix before ANY user data is live

None currently open.

---

## High — Must fix before beta launch

### H1: Render automatic snapshots not confirmed
- **Risk:** If prod DB is lost, only the last manual backup is available. Free-tier Render has no automatic snapshots.
- **Action:** Upgrade Render PostgreSQL to a paid plan with daily automatic backups, OR schedule a manual `pg_dump` cron job.
- **Effort:** 30 min (plan upgrade) or 1 hr (cron setup)
- **Ref:** `BACKUP_VALIDATION_REPORT.md`

### H2: Full backup restore drill not performed
- **Risk:** Backup commands are validated syntactically but never tested end-to-end against a real restore.
- **Action:** Restore prod backup to a scratch Render DB; run table count queries; verify dashboard loads.
- **Effort:** 1–2 hrs
- **Ref:** `BACKUP_VALIDATION_REPORT.md`

### H3: API_KEY in prod `.env` — manual verification needed
- **Risk:** Default fallback is `"changeme"`. If `.env` is not set on Render, all admin API calls would accept a known-public key.
- **Action:** Confirm `API_KEY` is set in Render environment variables and rotated from the default.
- **Effort:** 5 min (check Render dashboard)
- **Ref:** `PRODUCTION_AUDIT.md`

---

## Medium — Should fix shortly after launch

### M1: Content-Security-Policy header not set
- **Risk:** A stored XSS payload would execute with no browser-level mitigation. XSS vulnerabilities have been manually reviewed but no dynamic CSP protection.
- **Action:** Add `Content-Security-Policy` header in `add_security_headers`. Start with `default-src 'self'; script-src 'self' 'unsafe-inline'; ...`. Tighten to nonces after JS is modularized.
- **Effort:** 1–2 hrs
- **Ref:** `PRODUCTION_AUDIT.md`

### M2: Rate limiting not shared across workers
- **Risk:** If Render scales to multiple workers, the in-process rate limiter does not enforce limits globally.
- **Action:** Add Redis-backed rate limiting (e.g. flask-limiter with Redis storage) before scaling past 1 worker.
- **Effort:** 2–4 hrs
- **Ref:** `PRODUCTION_AUDIT.md`, `QUERY_PERFORMANCE_REPORT.md`

### M3: `get_active_loans` has no row cap
- **Risk:** At 1,000+ active loans the reminder queue query is unbounded and will cause timeouts.
- **Action:** Add `LIMIT 1000` to `get_active_loans` in `services.py`; add a WARN log if the limit is hit.
- **Effort:** 30 min
- **Ref:** `QUERY_PERFORMANCE_REPORT.md`

### M4: Log retention — 7 days on free Render tier
- **Risk:** Prod errors older than 7 days are unrecoverable from Render logs.
- **Action:** Connect a log drain (Papertrail, Logtail, etc.) to extend retention.
- **Effort:** 1 hr
- **Ref:** `ERROR_LOGGING.md`

### M5: Prod restore drill for schema parity
- **Risk:** 23 indexes were missing from prod when Sprint 6 ran the schema parity check. They were applied via `CREATE INDEX IF NOT EXISTS`, but no post-apply verification was confirmed.
- **Action:** Run `\d loans` in psql on prod and verify all `schema.sql` indexes exist.
- **Effort:** 15 min
- **Ref:** `SCHEMA_PARITY_REPORT.md`

---

## Low — Future improvements

### L1: CSRF token library
- **Status:** `SameSite=Lax` + XHR-only state changes give adequate protection today.
- **Action:** Add flask-wtf CSRF tokens if traditional form submissions are ever added.

### L2: Content Security Policy nonces
- **Status:** Blocked on modularizing inline `<script>` blocks.
- **Action:** Move all `<script>` to external `.js` files; replace `unsafe-inline` with nonces.

### L3: Reddit OAuth (auth hardening)
- **Status:** Intentionally deferred. Bot uses session-based login only.
- **Action:** Evaluate post-beta when borrower self-service is scoped.
- **RULE:** Do NOT implement Reddit OAuth until explicitly approved.

### L4: Admin metrics not available to mods without `can_view_money`
- **Status:** By design — metrics include loan dollar amounts. Only admins see full metrics.
- **Action:** Consider a limited "loan counts only" metrics view for mods.

### L5: Pagination on `/api/loans` capped at 200
- **Status:** Fine for beta. Will need cursor-based pagination at scale.
- **Action:** Add cursor or keyset pagination when loan volume exceeds 500 active loans.

---

## Pre-launch checklist summary

| # | Item | Status |
|---|---|---|
| H1 | Render automatic backups enabled | Pending |
| H2 | Full restore drill completed | Pending |
| H3 | `API_KEY` confirmed in Render env | Pending (manual check) |
| M1 | CSP header added | Deferred |
| M2 | Redis rate limiting | Deferred (post-scale) |
| M3 | `get_active_loans` LIMIT added | Deferred |
| M4 | Log drain connected | Deferred |
| M5 | Prod index presence verified | Pending (manual check) |
| — | All 225 tests passing | Done |
| — | Session cookies hardened | Done |
| — | Security headers applied | Done |
| — | `/health` endpoint live | Done |
| — | Admin metrics dashboard | Done |
| — | Permission attack surface reviewed | Done |
| — | Schema parity resolved | Done |
