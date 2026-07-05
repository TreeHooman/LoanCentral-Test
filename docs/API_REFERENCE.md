# API_REFERENCE.md

All routes live in `api/app.py`. Two auth mechanisms:

1. **Session** — Flask session cookie from key login (`/auth/key`), borrower
   OTP, or dev login (dev env only).
2. **Master API key** — `X-API-Key` request header, compared via
   `_api_key_ok()`. Header-only (query-string keys were removed). Key auth is
   disabled entirely if `API_KEY` is unset or "changeme". The master key
   passes every decorator (full admin power) — guard it accordingly.

## Decorators

| Decorator | Grants access to | Failure |
|---|---|---|
| `login_required` | any session | redirect `/login` |
| `role_required(*roles)` | session with role in list | redirect home + flash |
| `admin_required` / `mod_required` | aliases: `("admin")` / `("mod","admin")` | " |
| `verified_lender_required` | verified lender (DB-checked via `perm_version`), mod, admin | redirect |
| `require_auth` | master key OR any session (handler must scope!) | 401 JSON |
| `require_mod_api` | master key OR mod/admin session | 403 JSON |
| `require_admin_api` | master key OR admin session | 403 JSON |

Convention: JSON API under `/api/*` returns `_json({...}, status)`; HTML pages
redirect. Admin-tier JSON = `require_admin_api`; mod-tier = `require_mod_api`.

## Public (no auth)

`/`, `/terms`, `/login`, `/login/borrower`, `/auth/key`, `/health`,
`/api/announcements` (active only), `/auth/logout`.
- `/api/auth/borrower/claim` + `/verify` — OTP login, per-IP rate-limited.
- `/view/<token>`, `/view/<token>/calendar.ics` — magic-link read-only borrower view.
- `/auth/dev-login`, `/auth/dev-login-as/<u>` — `IS_DEV` only (no-op in prod).
- `/auth/reddit`, `/auth/callback` — inert; OAuth not configured by policy.

## User-tier (`require_auth` — handlers scope to caller)

- Loans: `GET /api/loans` (non-privileged → own loans only),
  `GET /api/loans/export.csv`, `GET/api detail /api/loans/<id>`,
  `PUT /api/loans/<id>/terms`, `POST /api/loans/create`,
  `POST /api/loans/bulk-paid`, and per-loan actions:
  `/paid`, `/unpaid`, `/refunded`, `/dispute`, `/acknowledge`,
  `/report-payment`, `/notes`, `/attachments` (GET/POST + download),
  `/events` (GET), `/calendar.ics`.
- Requests (NEW system): `POST /api/loan-requests`,
  `GET /api/loan-requests/mine`, `GET /api/loan-requests/<id>`,
  `GET /api/loan-requests/<id>/events`.
- Requests (OLD system, deprecated): `GET /api/requests`,
  `GET /api/requests/<id>`, `/note`, `/fund`, `/cancel`.
- Misc: `GET /api/users/<u>` (profile-visibility rules),
  `GET /api/stats`, `GET /api/stats/lender/<l>`, `GET /api/reminders`,
  `POST /api/verification/apply`, `GET+POST /api/feedback`,
  `GET/PUT /api/notifications/preferences`.
- Session-only: `GET /api/users/me`, `GET /api/session`,
  `GET /api/notifications`, `POST /api/notifications/read`.

## Mod-tier (`require_mod_api` JSON / `role_required("mod","admin")` pages)

- Pages: `/admin`, `/mod/queue`, `/admin/health`, `/admin/feedback`,
  `/admin/lenders/management`, `/admin/borrowers`, `/dashboard/mod`,
  `/dashboard/mod/{requests,request-review,disputes,risk,investigation/<u>}`,
  `/dashboard/admin/{audit-log,search}`, `/audit/user/<u>`.
- JSON: roles (`/api/admin/roles*`), verification queue + decisions,
  verified-lender get/set, reddit-actions queue (list/ban/status),
  audit log + user timelines/summaries, mod notes CRUD, disputes, risk,
  mod queue, announcements CRUD, feedback review, borrower contact +
  magic links, reddit-link get/set/delete, integrity, activity,
  `/api/loan-requests` (list/search/status/link/duplicates),
  `/api/requests/expire`.

## Admin-tier (`require_admin_api` JSON / `admin_required` pages)

- Pages: `/dashboard/admin`, `/dashboard/admin/keys`,
  `/dashboard/admin/lenders*`, `/admin/request-analytics`,
  `/admin/communications`.
- JSON: `/api/admin/keys*` (list/create/revoke), `/api/admin/lenders*`,
  `/api/admin/metrics*`, `/api/admin/analytics`,
  `/api/admin/request-analytics`, `/api/admin/notifications/purge`,
  `/api/admin/notifications/queue*` (list/stats/reminders),
  `/api/admin/requests/{expire,flag-duplicates,missing-threads,unlinked-funded,quality-report,backfill}`.

## Special

- `/dashboard/lender` — `verified_lender_required`.
- `/dashboard/borrower`, `/feedback` — `login_required`.
- `/dashboard/users/<u>` — login + `_can_view_user_profile` (self, mod/admin,
  or shared-loan counterparty).
- `/dashboard/borrower/requests`, `/dashboard/requests/<id>` —
  `role_required("borrower","lender","mod","admin")` (any known role).

Last audited: 2026-07-05 — docs/reports/AUTHZ_AUDIT_2026-07-05.md.
