# LoanCentral Expansion Plan

## Current State (Sprint 10 complete)

The platform is feature-complete for beta operations. Core systems are in place:
- Loan tracking, role management, verification workflow
- Mod/admin tooling: queue, audit investigation, community health, lender/borrower dashboards
- Feedback collection, announcement system, notification preferences
- 342 passing tests

---

## Beta Phase Objectives

### 1. Gather Beta Feedback

Use the built-in feedback system (`/feedback`) to collect structured input. Prioritize:
- **Bugs** — anything blocking normal use
- **UX friction** — steps that are confusing or slow
- **Missing features** — gaps lenders/borrowers report repeatedly

Review `/admin/feedback` weekly during beta. Close feedback items by category and track patterns.

### 2. Monitor Community Health

Use `/admin/health` with the 7/30/90-day views to track:
- Loan volume trend — is it growing?
- Unpaid rate — is it stable or rising?
- Verification approvals — is the lender pipeline healthy?
- Active user count — are users returning?

Flag anomalies in the audit log and investigate via `/audit/user/<username>`.

### 3. Stabilize Onboarding

Current onboarding cards are dismissable. Track whether new users actually use the platform after first login:
- Count users with `last_login` > 1 day after `created_at` (returning users)
- If drop-off is high, improve the onboarding card copy or add an email welcome

---

## Launch Blockers (must resolve before public launch)

Refer to `PUBLIC_LAUNCH_CHECKLIST.md` for the full list. Key items:

| Blocker | Owner | Notes |
|---------|-------|-------|
| Reddit OAuth | Deferred | Do not implement until dashboard is stable |
| Email OTP reliability | Ops | Test delivery rates with real users |
| Rate limiting on API | Eng | Add `flask-limiter` or nginx rate limits before public |
| Security review of session handling | Eng | Verify `SESSION_COOKIE_SECURE=True` in prod |

---

## Lender Growth Process

New lenders go through the verification workflow:
1. User registers and submits verification application
2. Mod reviews at `/verification` tab or `/mod/queue`
3. Approved → `verified_lender=TRUE`, lender dashboard unlocked

During beta: mods handle all verifications manually.
Post-launch: consider automated pre-screening (account age, karma checks) as an optional helper — final decision remains with mods. No automated approval.

---

## Borrower Onboarding

Borrowers self-register. No verification required by default.

Post-launch options (if needed):
- Require email verification before first loan request
- Add borrower profile completeness score (internal only, not shown to users)
- Allow lenders to leave structured feedback per loan (separate from the public feedback system)

---

## Community Expansion

If the subreddit grows and volume increases:

| Volume Threshold | Action |
|-----------------|--------|
| 50+ active loans | Add pagination everywhere (already in place) |
| 100+ lenders | Consider lender tiers (not credit scoring — just activity badges) |
| 5+ mods | Add per-mod workload visibility to `/mod/queue` |
| High feedback volume | Add feedback tagging/labeling for faster triage |

---

## Deferred Features (do not build until explicitly requested)

- **Reddit OAuth** — deferred, DB is source of truth for permissions
- **Automated Reddit flair sync** — requires live Reddit API integration
- **Credit scoring or risk rating** — hard rule: never implement
- **Lender-borrower matching** — hard rule: never implement
- **Debt collection integration** — hard rule: never implement

---

## Technical Debt to Address Before Scale

1. **Database indexes** — audit `loans` and `user_roles` query patterns under load; add indexes as needed
2. **Connection pooling** — `_get_db()` opens a new connection per request; add `psycopg2.pool` or `pgbouncer` before high traffic
3. **Error monitoring** — integrate Sentry or similar to catch prod exceptions automatically
4. **Automated DB backups** — verify Render backup retention is sufficient; add `pg_dump` cron if not

---

## Timeline (rough)

| Phase | Milestone |
|-------|-----------|
| Now | Beta with trusted lenders/borrowers |
| +4 weeks | First feedback review, fix critical bugs |
| +8 weeks | Evaluate launch readiness against checklist |
| +12 weeks | Public launch if checklist clears |
| Post-launch | Monitor health dashboard weekly, iterate on feedback |
