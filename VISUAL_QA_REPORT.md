# LoanCentral — Visual QA Report
Sprint 3 | Date: 2026-06-09

## Scope
Static code review of all dashboard templates. No live server required.
Templates reviewed:
- `api/templates/base.html` (1347+ lines)
- `api/templates/dashboard_lender.html` (822 lines)
- `api/templates/dashboard_mod.html` (857+ lines)
- `api/templates/audit_log.html`
- `api/templates/global_search.html`

---

## Issues Found & Fixed

| # | Page/Template | Issue | Severity | Fix Applied |
|---|---------------|-------|----------|-------------|
| 1 | `base.html` — `loadLoanTimeline()` | `escapeHtml()` called at lines 1112–1114 but never defined in `base.html`. Only defined in sub-template block scripts. Any dashboard using the loan timeline modal would throw `ReferenceError: escapeHtml is not defined` at runtime. | **High** | Added `escapeHtml(s)` function definition in `base.html` main `<script>` block, before `apiFetch`. |
| 2 | `base.html` — `submitNewLoan()` | `result` variable assigned inside `if/else` branches without a preceding `let result;` declaration. In strict mode (or with linters) this is a `ReferenceError`; in sloppy mode it silently creates a global. | **Medium** | Added `let result;` at the top of `submitNewLoan()`. |
| 3 | `base.html` — `submitNewLoan()` | `session_user` referenced on line 1046 (`lender: ME \|\| session_user`) but never defined anywhere in the template. Would resolve to `undefined`, silently sending `lender: undefined` to the API, which then rejects the request. | **Medium** | Removed `\|\| session_user` — `ME` is sufficient (set by each sub-template that uses this modal). |
| 4 | `global_search.html` — loan results | Loan ID links pointed to `/api/loans/${l.loan_id}` — a JSON API endpoint, not a user-facing page. Clicking would show raw JSON instead of navigating. | **Low** | Changed link to `/dashboard/users/${encodeURIComponent(l.lender)}` — navigates to the lender's user profile. |

---

## Issues Not Fixed (Deferred)

| # | Template | Issue | Reason Deferred |
|---|----------|-------|-----------------|
| 1 | `dashboard_mod.html` | No mobile-specific layout testing done. Multi-tab dashboard is complex on small screens. | Requires live server + device emulation. |
| 2 | `dashboard_lender.html` | `escapeHtml` is defined locally at line 731 — now redundant given the shared definition in `base.html`. Harmless (the local definition shadows the shared one with identical behaviour), but could be cleaned up. | Minor housekeeping, low risk. |
| 3 | All dashboards | Dark/light mode visual consistency not verified — CSS variables may produce low-contrast text in some combinations. | Requires visual review with browser. |

---

## Notes
- All four fixes are in pure JS/HTML — no backend changes needed.
- `escapeHtml` fix is the highest-risk item: any user-supplied data rendered in the loan timeline modal (event types, actor usernames, detail text) was previously unescaped, creating a potential stored-XSS vector if those fields ever contained `<script>` content.
- Fix 4 (search links) is a UX issue only — no security impact.
