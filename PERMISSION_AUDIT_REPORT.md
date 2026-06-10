# Permission Audit Report — Sprint 6
Date: 2026-06-09

## Method
Every sensitive route was exercised through the Flask test client as: anonymous, borrower, lender (unverified), mod, and admin. Automated regression tests live in `tests/test_sprint6.py` (`RoutePermissionTests`). Database permissions remain the only source of truth; Reddit flair is never consulted.

## Decorator model
| Decorator | Grants | Notes |
|---|---|---|
| `login_required` | any session | redirects anonymous to login |
| `role_required(*roles)` | listed roles only | redirects others (pages) |
| `require_auth` | API key or any session | per-loan checks inside handlers |
| `require_mod_api` | API key, mod, admin | JSON 403 otherwise |
| `require_admin_api` | API key, admin | JSON 403 otherwise |
| `verified_lender_required` | VL/mod/admin, perm_version-aware | re-checks DB when perm_version changes |

## Route matrix (verified behavior)
| Route | Anonymous | Borrower | Lender | Mod | Admin |
|---|---|---|---|---|---|
| /dashboard/admin | redirect | redirect | redirect | redirect | ✓ |
| /dashboard/admin/lenders (new) | redirect | redirect | redirect | redirect | ✓ |
| /dashboard/admin/lenders/&lt;u&gt; (new) | redirect | redirect | redirect | redirect | ✓ |
| /api/admin/lenders (new) | 403 | 403 | 403 | 403 | ✓ |
| /api/admin/lenders/&lt;u&gt; (new) | 403 | 403 | 403 | 403 | ✓ |
| /api/admin/verified-lender (POST) | 403 | 403 | 403 | ✓ | ✓ |
| /api/admin/users/&lt;u&gt;/reddit-link | 403 | 403 | 403 | ✓ | ✓ |
| /api/admin/audit-log | 403 | 403 | 403 | ✓ | ✓ |
| /api/admin/search | 403 | 403 | 403 | ✓ | ✓ |
| /api/admin/roles | 403 | 403 | 403 | ✓ | ✓ |
| /api/admin/integrity | 403 | 403 | 403 | ✓ | ✓ |
| /api/admin/keys (GET) | 403 | 403 | 403 | 403 | ✓ |
| /api/admin/keys (POST/revoke) | deny | deny | deny | deny | ✓ (session only) |
| /api/notifications | 302/401 | own only | own only | own only | own only |
| /api/loans/&lt;id&gt;/calendar.ics | 401 | own loans only | own loans only | ✓ | ✓ |

Mod denial on the lender directory is **intentional** — it surfaces aggregate money figures, which are admin-scope (mods get `can_view_money=False` on their dashboard).

## Gaps found and fixed
1. **`/api/admin/integrity` locked out admins** — used `@role_required("mod")`, which permits only the literal role `mod`. Admins were redirected. Fixed to `@require_mod_api` (mod + admin + API key). Regression test: `test_integrity_admin_allowed`.
2. **`/api/admin/keys` (GET) returned a 302 redirect instead of JSON 403** for non-admin API callers. Fixed to `@require_admin_api`. Key *mutations* (create/revoke) intentionally remain session-only `role_required("admin")` so a leaked API key cannot mint lender keys.

## Defense-in-depth notes
- Sensitive POSTs that depend on verified-lender status re-check the DB via `perm_version` (`verified_lender_required`) or `_is_lender_verified_fresh`, bounding session staleness to one request.
- Verification `private_note` is excluded from the lender directory, admin profile, and global search by construction (asserted in tests).
- Notification read endpoints only operate on `session["username"]` — no user parameter is accepted, so cross-user reads are impossible by design.
- Money fields are redacted for mods via `_redact_*` helpers; admin lender directory is admin-only for this reason.

## Residual risks / future work
- `require_auth` accepts a single static `API_KEY` env var; per-lender API keys exist (`lender_keys`) but are not yet enforced per-route. Tracked in memory/project_auth_future.md.
- Reddit OAuth deliberately not implemented (per project constraints).
