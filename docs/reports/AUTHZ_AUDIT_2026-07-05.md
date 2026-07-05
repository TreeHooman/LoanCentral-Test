# Authorization Enforcement Audit — 2026-07-05

Scope: every Flask route in `api/app.py` (~147 routes) + every bot command in
`commands/`. Question asked of each: is the caller's permission checked against
the **DB** (never Reddit flair), are API keys header-only, and is the response
scoped to what the caller may see?

## Verdict

**PASS** with 2 issues found and fixed in this audit (see below). No
unauthenticated data-leak paths found.

## Route coverage

Every route carries one of the standard decorators, or is intentionally public:

| Class | Decorator | Notes |
|---|---|---|
| Mod/admin HTML pages | `@role_required("mod","admin")` / `@admin_required` | redirect to /login or home |
| Admin JSON API | `@require_admin_api` | master key or admin session |
| Mod JSON API | `@require_mod_api` | master key or mod/admin session |
| User JSON API | `@require_auth` | master key or any session; handlers scope results to caller |
| Lender dashboard | `@verified_lender_required` | DB-backed, perm_version cache-busting on revocation |
| Borrower pages | `@login_required` | |

Intentionally public (verified each):

- `/`, `/terms`, `/login`, `/login/borrower`, `/auth/key`, `/health` — static/login surface, no user data.
- `/auth/dev-login`, `/auth/dev-login-as/<u>` — hard-gated by `IS_DEV` (`LOANCENTRAL_ENV != "prod"`; env defaults to `"prod"`, so prod is closed unless the env var is deliberately changed).
- `/api/auth/borrower/claim|verify` — OTP flow; rate-limited per IP (429 after threshold), contact masked in response.
- `/view/<token>`, `/view/<token>/calendar.ics` — magic-link; `validate_magic_link` gates, 403 on invalid/expired.
- `/api/announcements` — active announcements only, public by design.
- `/auth/reddit`, `/auth/callback` — inert unless `oauth_configured()`; not configured per standing rule 1.

## Scoping spot-checks (all OK)

- `/api/loans` — non-privileged callers scoped to own history (the 2026-06-25 IDOR fix, verified still in place).
- `/api/loans/<id>` and `/api/loans/<id>/calendar.ics` — 403 unless lender/borrower on that loan or mod/admin.
- `/dashboard/users/<username>` — `_can_view_user_profile`: self, mod/admin, or shared-loan counterparty only.
- `/api/reminders` — scoped to caller.
- Money mutations (`mark_repaid`, etc.) re-verify actor vs. the loan's recorded lender/borrower inside `services.py` (case-insensitive), so even an authenticated caller can't act on someone else's loan.

## Bot commands

- `$loan`, `$fund`, `$paid_with_id`, `$unpaid`, `$refund` — all gated by `require_verified_lender`: **DB `verified_lender` status is the primary gate**; Reddit flair is a second *restrictive* gate (flair can only deny, never grant → complies with "DB is source of truth").
- Per-loan ownership enforced in services (e.g. `mark_repaid` rejects a verified lender who isn't the loan's lender).
- `$dispute` (borrower-initiated), `$logi` (read-only stats), `$help` — appropriately open.

## API keys

- Header-only (`X-API-Key`) everywhere; query-string fallback confirmed absent.
- All key comparisons go through one helper (`_api_key_ok`, added in this audit).

## Issues found & fixed (this audit)

1. **Admins locked out of two mod endpoints** — `/api/admin/borrower-contact/<u>` and `/api/admin/send-magic-link/<u>` used `@role_required("mod")`, which excludes the `admin` role (every other mod route uses `("mod","admin")`). Availability bug, not a leak. **Fixed:** both now `@role_required("mod","admin")`.
2. **"changeme" master-key fallback** — `API_KEY = os.getenv("API_KEY", "changeme")`: if the env var ever went missing in prod, every `require_*` decorator would accept `X-API-Key: changeme`. Prod currently has a real key set, but defense-in-depth: **Fixed** — key auth is now disabled entirely (`API_KEY_AUTH_ENABLED`) when API_KEY is unset/empty/"changeme"; all 5 comparison sites route through `_api_key_ok()`.

## Accepted risks (known, deliberate)

- Legacy `/api/requests` open board is visible to lenders **by design**; legacy `/api/requests/<id>` has a minor scoping inconsistency — deprecated, superseded by `/api/loan-requests/*`, left as-is per 2026-06-25 decision.
- `role_required` trusts the session-cached role; a demotion takes effect at next login (perm-version freshness is implemented only for verified-lender status, which gates money actions). Bounded, acceptable pre-launch.
- The master API key is a single shared secret with full admin power. Per-lender scoped API keys exist in the roadmap (`/api/admin/keys` scaffolding present); revisit before opening the API to third parties.
