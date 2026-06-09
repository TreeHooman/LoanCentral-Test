# Beta Readiness Report — LoanCentral
**Date:** 2026-06-09  
**Sprint:** 5 (final pre-beta)

---

## Executive Summary

LoanCentral is **ready for private beta**. All critical platform features are implemented, the test suite passes at 138/138, and security controls are in place. The items marked ⚠️ below are known, intentional deferrals — not blockers.

---

## Feature Checklist

### Authentication & Access Control
| Item | Status | Notes |
|------|--------|-------|
| Flask session-based auth | ✅ Done | All protected routes decorated |
| `perm_version` staleness check | ✅ Done | Session cache invalidated on permission change |
| `_is_lender_verified_fresh()` | ✅ Done | DB-direct check on sensitive POST actions |
| Role-based decorators | ✅ Done | `verified_lender_required`, `role_required`, `require_auth`, `require_mod_api`, `require_admin_api` |
| OTP brute-force rate limit | ✅ Done | 5 attempts / 15-min window per IP |
| Reddit OAuth | ⚠️ Deferred | Per design spec — not needed for beta |
| Lender API key auth | ⚠️ Deferred | See `project_auth_future.md` |

### Loan Management
| Item | Status | Notes |
|------|--------|-------|
| Create / confirm loans | ✅ Done | |
| Mark repaid / unpaid | ✅ Done | |
| Partial repayment | ✅ Done | |
| Dispute workflow | ✅ Done | |
| Loan event timeline | ✅ Done | `loan_events` table + timeline UI |
| Calendar ICS export | ✅ Done | Add-to-Calendar button in loan detail modal |

### Notifications
| Item | Status | Notes |
|------|--------|-------|
| Notification bell + panel | ✅ Done | Live unread count in `base.html` |
| `create_notification()` service | ✅ Done | Non-raising, used throughout |
| Loan confirmed notification | ✅ Done | Both lender and borrower notified |
| Loan unpaid notification | ✅ Done | Borrower notified |
| Dispute opened notification | ✅ Done | Lender notified |
| Verification approved/denied/more_info | ✅ Done | Applicant notified on all outcomes |

### Lender Verification
| Item | Status | Notes |
|------|--------|-------|
| Verification application (lender dashboard) | ✅ Done | |
| Verification application (borrower dashboard) | ✅ Done | |
| Mod verification queue | ✅ Done | Status filter, 8-column table |
| Approve / Deny / More Info decisions | ✅ Done | `more_info` sets status back to pending |
| `set_verified_lender` called on approval | ✅ Done | DB flag + `verified_lender_at`/`by` |
| Revoke Verified Lender status | ✅ Done | Mod can revoke via dashboard |
| Verified Lender badge in profile | ✅ Done | Shows date and approver |
| Verified Lender badge in lender dashboard | ✅ Done | |
| Verification audit log | ✅ Done | All decisions logged to `audit_logs` |

### Reddit Username Linking
| Item | Status | Notes |
|------|--------|-------|
| Manual mod-only linking | ✅ Done | `/api/admin/users/<username>/reddit-link` |
| Unlink support | ✅ Done | |
| Duplicate username blocked | ✅ Done | |
| Normalized (u/ stripped) | ✅ Done | |
| Shown in mod roles table | ✅ Done | |
| Shown in verification queue | ✅ Done | |
| Shown in global search | ✅ Done | |
| Shown in user profile | ✅ Done | Links to reddit.com |
| Reddit flair NOT trusted | ✅ Confirmed | DB is sole source of truth |

### Mod Tools
| Item | Status | Notes |
|------|--------|-------|
| Audit log viewer | ✅ Done | `audit_logs` + `audit_events` |
| Verified Lender management | ✅ Done | Set/revoke with note |
| Global search | ✅ Done | Loans + users; matches reddit_username |
| User roles table | ✅ Done | Shows reddit_username column |
| Notification center | ✅ Done | Bell + panel + mark-read |

### Data & Database
| Item | Status | Notes |
|------|--------|-------|
| SQLite dev database | ✅ Done | `_ensure_column` migration pattern |
| PostgreSQL production-ready schema | ✅ Done | `schema.sql` |
| `reddit_username` columns added | ✅ Done | `schema.sql` + `local_db.py` migration |
| Three audit systems | ✅ Done | `audit_events`, `audit_logs`, `loan_events` |

---

## Security Controls

| Control | Status |
|---------|--------|
| All mod/admin routes require `require_mod_api` / `require_admin_api` | ✅ |
| Permission changes invalidate session via `perm_version` | ✅ |
| Sensitive actions use `_is_lender_verified_fresh()` (DB-direct) | ✅ |
| OTP rate limiter (5 req / 15 min / IP) | ✅ |
| Reddit flair ignored — DB is source of truth | ✅ |
| No production credentials modified during development | ✅ |
| No live Reddit API changes made | ✅ |
| XSS: `escapeHtml()` in all templates | ✅ |
| CSRF: session-bound API calls | ✅ |

---

## Test Coverage

| File | Tests | Status |
|------|-------|--------|
| `test_services.py` | ~30 | ✅ 138/138 |
| `test_auth.py` | ~14 | ✅ |
| `test_loans.py` | ~12 | ✅ |
| `test_sprint3.py` | 24 | ✅ |
| `test_sprint4.py` | 14 | ✅ |
| `test_sprint5.py` | 15 | ✅ |
| **Total** | **138** | **✅ 138 passed, 1 warning** |

The single warning is a `datetime.utcnow()` deprecation in the ICS calendar route — cosmetic, not a defect.

---

## Known Deferrals (Not Beta Blockers)

1. **Reddit OAuth** — intentionally deferred. Manual reddit username linking covers beta needs.
2. **Lender API keys** — deferred per `project_auth_future.md`.
3. **Borrower auth** — deferred per `project_auth_future.md`.
4. **`datetime.utcnow()` in ICS route** — cosmetic deprecation warning; behavior correct.

---

## Recommendation

**Proceed to private beta.** All core loan lifecycle features, mod tools, verification workflows, notifications, and security controls are implemented and tested.
