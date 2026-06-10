# LoanCentral — Public Launch Checklist

Last updated: 2026-06-09

---

## Platform Verification

### Core Functionality
- [ ] Loan creation works end-to-end (lender dashboard → Record Loan)
- [ ] REQ-ID lookup auto-fills loan modal
- [ ] Mark Paid / Unpaid / Refunded all update loan status correctly
- [ ] Repayment date edit (extension) saves correctly
- [ ] Loan notes and attachments save and display
- [ ] Loan timeline events recorded for each status change
- [ ] Calendar export (.ics) generates valid file

### Verification Workflow
- [ ] Lender can submit verification application
- [ ] Mod can approve / deny with note
- [ ] Verified badge appears on lender dashboard after approval
- [ ] Verification history visible in audit log

### Search
- [ ] Global search returns loans by ID
- [ ] Global search returns users by username
- [ ] Global search returns REQ-IDs
- [ ] Empty search returns helpful guidance (not blank page)

### Notifications
- [ ] In-app notification bell shows unread count
- [ ] Mark-read and mark-all-read work
- [ ] Notification preferences save and persist across sessions
- [ ] Purge endpoint removes old read notifications

### Audit Logs
- [ ] All dashboard mod/admin actions produce audit entries
- [ ] Audit log filters work (actor, action, target, date)
- [ ] User activity timeline loads for a known user
- [ ] Audit log empty state shows helpful message

### Admin Tools
- [ ] Admin metrics endpoint returns correct counts
- [ ] Expanded metrics include monthly loan/repayment counts
- [ ] Admin roles page paginates correctly
- [ ] Admin feedback dashboard loads and filters work
- [ ] API key management page works (create, revoke)

### Feedback System
- [ ] Users can submit bug reports, suggestions, feature requests
- [ ] Submissions appear in user's own feedback list
- [ ] Mod/admin can review and update status in feedback dashboard
- [ ] Reviewer note visible to submitter after update

---

## Security & Access Control

- [ ] Unauthenticated requests to /api/* return 401 or redirect
- [ ] Borrower cannot access lender-only or mod-only routes
- [ ] Lender cannot access mod/admin routes
- [ ] API key header (X-API-Key) enforced on bot-facing endpoints
- [ ] Session cookies: HttpOnly, SameSite=Lax, Secure in prod
- [ ] Security headers present: X-Content-Type-Options, X-Frame-Options, Referrer-Policy, HSTS (prod)
- [ ] OTP rate limiting active (5 attempts per IP per 15 min)
- [ ] No Reddit OAuth implemented (DB is source of truth for roles)
- [ ] No Reddit flair trusted for permissions

---

## Infrastructure

### Backups (Render)
- [ ] **H1** — Confirm automatic snapshots are enabled in Render dashboard
- [ ] **H2** — Perform a full restore drill from a recent snapshot to a staging DB
- [ ] Backup validation report reviewed (BACKUP_VALIDATION_REPORT.md)

### Environment
- [ ] **H3** — Verify `API_KEY` env var in Render is set to a strong secret (not "changeme")
- [ ] `SECRET_KEY` env var set to a strong secret
- [ ] `LOANCENTRAL_ENV=prod` set in Render
- [ ] `DB_*` / `DATABASE_URL` pointing to production database

### Monitoring
- [ ] `/health` endpoint returns `{"status":"ok"}` in production
- [ ] Uptime monitor configured to poll `/health` every 5 minutes
- [ ] Error logging active (check Render logs after a test action)

---

## Beta Readiness

- [ ] At least one end-to-end loan recorded, repaid, and archived in prod
- [ ] At least one lender verification approved through the workflow
- [ ] Mod team briefed on verification queue and audit log usage
- [ ] Feedback system tested — submit one of each category
- [ ] Onboarding cards reviewed on borrower, lender, and mod dashboards
- [ ] Empty states confirmed on: loans, notifications, search, audit, feedback
- [ ] Beta feedback reviewed and critical bugs resolved

---

## Known Deferred Items (Post-Beta)

| ID | Item | Priority |
|----|------|----------|
| M1 | CSP header not set | Medium |
| M2 | Rate limiting not shared across workers | Medium |
| M3 | `get_active_loans` has no LIMIT | Medium |
| L1 | Per-lender API key enforcement per-route | Low |
| L2 | Reddit OAuth for broader borrower access | Low (deferred) |

---

## Sign-off

- [ ] All tests passing (`python -m pytest tests/ -q`)
- [ ] H1 / H2 / H3 blockers resolved
- [ ] Launch checklist reviewed by at least one mod
- [ ] Go / No-Go decision recorded here: _______________
