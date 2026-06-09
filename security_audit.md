# LoanCentral Security Audit
Generated: 2026-06-09

## Summary

| Category | Count |
|----------|-------|
| Protected routes | 49 |
| Public / auth routes (intentionally open) | 14 |
| Recommendations | 4 |

---

## Protected Routes

All routes below have at least one access-control decorator applied.

### Admin-only (`@role_required("admin")`)
| Route | Method | Decorator |
|-------|--------|-----------|
| `/dashboard/admin/keys` | GET | `role_required("admin")` |
| `/api/admin/keys` | GET | `role_required("admin")` |
| `/api/admin/keys` | POST | `role_required("admin")` |
| `/api/admin/keys/<key_id>/revoke` | POST | `role_required("admin")` |
| `/dashboard/admin` | GET | `role_required("admin")` |

### Mod or Admin (`@role_required("mod","admin")` / `@require_mod_api`)
| Route | Method | Decorator |
|-------|--------|-----------|
| `/api/admin/borrower-contact/<username>` | POST | `role_required("mod")` |
| `/api/admin/send-magic-link/<username>` | POST | `role_required("mod")` |
| `/api/admin/integrity` | GET | `role_required("mod")` |
| `/dashboard/mod` | GET | `role_required("mod","admin")` |
| `/api/admin/roles/<username>` | GET | `require_mod_api` |
| `/api/admin/roles/<username>` | POST | `require_mod_api` |
| `/api/admin/roles` | GET | `require_mod_api` |
| `/api/integrations/reddit/status` | GET | `require_mod_api` |
| `/api/reddit-actions` | GET | `require_mod_api` |
| `/api/reddit-actions/ban` | POST | `require_mod_api` |
| `/api/reddit-actions/<action_id>/status` | POST | `require_mod_api` |
| `/api/activity` | GET | `require_mod_api` |
| `/api/verification` | GET | `require_mod_api` |
| `/api/verification/<id>/decision` | POST | `require_mod_api` |
| `/api/loans/<loan_id>/clear-unpaid` | POST | `require_mod_api` |
| `/api/requests/expire` | POST | `require_mod_api` |
| `/api/admin/audit-log` | GET | `require_mod_api` |
| `/dashboard/admin/audit-log` | GET | `role_required("mod","admin")` |
| `/api/loans/<loan_id>/events` | POST | `require_mod_api` |
| `/api/admin/verified-lender/<username>` | GET | `require_mod_api` |
| `/api/admin/verified-lender/<username>` | POST | `require_mod_api` |
| `/api/admin/search` | GET | `require_mod_api` |
| `/dashboard/admin/search` | GET | `role_required("mod","admin")` |

### Lender or higher (`@role_required("lender","mod","admin")`)
| Route | Method | Decorator |
|-------|--------|-----------|
| `/dashboard/lender` | GET | `role_required("lender","mod","admin")` |

### Any authenticated user (`@require_auth` / `@login_required`)
| Route | Method | Decorator |
|-------|--------|-----------|
| `/api/loans` | GET | `require_auth` |
| `/api/loans/export.csv` | GET | `require_auth` |
| `/api/loans/<loan_id>` | GET | `require_auth` |
| `/api/loans/<loan_id>/terms` | PUT | `require_auth` |
| `/api/loans/bulk-paid` | POST | `require_auth` |
| `/api/loans/<loan_id>/unpaid` | POST | `require_auth` |
| `/api/loans/<loan_id>/refunded` | POST | `require_auth` |
| `/api/loans/<loan_id>/dispute` | POST | `require_auth` |
| `/api/loans/<loan_id>/acknowledge` | POST | `require_auth` |
| `/api/loans/<loan_id>/report-payment` | POST | `require_auth` |
| `/api/loans/<loan_id>/paid` | POST | `require_auth` |
| `/api/loans/<loan_id>/attachments` | GET/POST | `require_auth` |
| `/api/loans/<loan_id>/attachments/<id>/download` | GET | `require_auth` |
| `/api/loans/create` | POST | `require_auth` |
| `/api/requests` | GET | `require_auth` |
| `/api/requests/<request_id>` | GET | `require_auth` |
| `/api/requests/<request_id>/note` | POST | `require_auth` |
| `/api/requests/<request_id>/fund` | POST | `require_auth` |
| `/api/requests/<request_id>/cancel` | POST | `require_auth` |
| `/api/stats` | GET | `require_auth` |
| `/api/stats/lender/<lender>` | GET | `require_auth` |
| `/api/reminders` | GET | `require_auth` |
| `/api/loans/<loan_id>/notes` | POST | `require_auth` |
| `/api/loans/<loan_id>/events` | GET | `require_auth` |
| `/api/users/<username>` | GET | `require_auth` |
| `/api/users/me` | GET | `login_required` |
| `/api/session` | GET | `login_required` |
| `/api/notifications` | GET | `login_required` |
| `/api/notifications/read` | POST | `login_required` |
| `/api/verification/apply` | POST | `require_auth` |
| `/dashboard/borrower` | GET | `login_required` |
| `/dashboard/users/<username>` | GET | `login_required` |

---

## Public / Auth Routes (Intentionally Open)

These routes are intentionally unauthenticated — they form the login flow or public pages.

| Route | Notes |
|-------|-------|
| `GET /` | Redirects to login if no session |
| `GET /login` | Login page |
| `GET /login/borrower` | Borrower OTP login page |
| `GET /terms` | Public terms of service |
| `GET /auth/reddit` | Initiates Reddit OAuth |
| `GET /auth/callback` | Reddit OAuth callback |
| `GET /auth/key` | Lender API key login (validates key before setting session) |
| `POST /api/auth/borrower/claim` | Step 1 of borrower OTP — validates loan ownership first |
| `POST /api/auth/borrower/verify` | Step 2 of borrower OTP — verifies code |
| `GET /view/<token>` | Magic link read-only borrower view — token validated server-side |
| `GET /view/<token>/calendar.ics` | Magic link calendar export — token validated server-side |
| `GET /auth/dev-login` | **Dev-only** — blocked in production (`IS_DEV` check) |
| `POST /auth/dev-login` | **Dev-only** — blocked in production |
| `GET /auth/dev-login-as/<username>` | **Dev-only** — blocked in production |
| `GET /auth/logout` | Clears session |

---

## Recommendations

1. **`/auth/dev-login` and `/auth/dev-login-as/`** — Confirm `IS_DEV` evaluates to `False` in production. Currently gated by `LOANCENTRAL_ENV != "prod"`. Before going live, verify the env var is set correctly on the server.

2. **`@require_auth` vs `@login_required`** — `require_auth` accepts both session AND `X-API-Key` header. Routes that should be session-only (e.g. `/api/users/me`, `/api/session`) correctly use `@login_required`. Review any new routes to pick the right one.

3. **`/api/loans/<loan_id>/unpaid` and `/refunded`** — Currently `@require_auth` with an internal lender-ownership check. These are write operations; consider upgrading to `@verified_lender_required` once lender verification is rolled out.

4. **New decorators available** — `@verified_lender_required`, `@mod_required`, `@admin_required` are now wired in. Apply `@verified_lender_required` to lender analytics routes when verification is enforced.
