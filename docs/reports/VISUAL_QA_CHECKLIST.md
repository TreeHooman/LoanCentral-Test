# Visual QA Checklist - LoanCentral
Date: 2026-06-09

Run this before private beta changes go live. Use the dev login shortcuts unless testing production auth.

## Setup
- [ ] Start the app locally.
- [ ] Open the dashboard in desktop width.
- [ ] Repeat key checks at mobile width.
- [ ] Confirm no browser console errors on each role dashboard.
- [ ] Confirm no secret values appear in page source or UI.

## Demo Users
- `hawtchili` - borrower dashboard with active and historical loans
- `logistix1` - lender dashboard with many recorded loans
- `testmod` - moderator dashboard
- `testadmin` - admin/owner dashboard

## Borrower - `hawtchili`
- [ ] Borrower dashboard loads.
- [ ] Current balance / repaid / standing summary renders.
- [ ] "What I Currently Owe" table/card list renders.
- [ ] Full loan history renders.
- [ ] Status filters work.
- [ ] Search filters loan ID or lender.
- [ ] Report Payment modal opens and validates required fields.
- [ ] Acknowledge button opens/submits correctly when available.
- [ ] Thread links open the expected Reddit thread.
- [ ] Mobile cards fit without horizontal scrolling.
- [ ] Mobile history "show more" behavior works when enough rows exist.

## Lender - `logistix1`
- [ ] Lender dashboard loads.
- [ ] Portfolio stats and due alerts render.
- [ ] Loan filters and sort menu work.
- [ ] Search filters borrower, loan ID, status, and notes.
- [ ] Record Loan modal opens.
- [ ] Request ID lookup works for an open REQ.
- [ ] Paid modal opens and validates required fields.
- [ ] Unpaid modal opens and validates lender.
- [ ] Refund modal opens for eligible loans.
- [ ] Extension/Edit Repayment Date opens and only saves with a chosen date.
- [ ] Files modal opens and attachment list renders.
- [ ] Notes modal opens and note preview is safe/escaped.
- [ ] Copy action copies or displays expected summary.
- [ ] Export CSV starts a download.
- [ ] Calendar download works for a loan with a due date.
- [ ] Mobile compact cards show Paid, Unpaid, Extension at the top.
- [ ] Tapping a mobile loan card expands additional info/actions.
- [ ] Button taps do not accidentally expand/collapse the card.
- [ ] Mobile view has no horizontal scrolling.

## Moderator - `testmod`
- [ ] Mod dashboard loads.
- [ ] Loan table renders and status tabs work.
- [ ] Search works by lender, borrower, or loan ID.
- [ ] Main mobile loan cards show compact commands.
- [ ] Tapping a mobile loan card expands lender/borrower/thread details.
- [ ] Unpaid review tab loads.
- [ ] Disputes tab loads.
- [ ] Reminder queue loads.
- [ ] Verification queue loads.
- [ ] More Info and decision controls render for verification records.
- [ ] Reddit action queue loads without making live Reddit calls.
- [ ] Role management loads and can search/add users in dev.
- [ ] Activity feed loads.
- [ ] Data integrity check page loads.
- [ ] Money fields are redacted where mod policy requires it.

## Admin - `testadmin`
- [ ] Admin dashboard loads.
- [ ] Admin navigation shows Search, Audit Log, Lenders, Keys.
- [ ] Global search page loads.
- [ ] Global search finds username.
- [ ] Global search finds reddit_username.
- [ ] Global search finds loan ID.
- [ ] Global search shows verification application group when matching.
- [ ] Search result links open admin lender profile where appropriate.
- [ ] Audit log page loads.
- [ ] Audit log filters work for actor, action, target, date, and loan ID.
- [ ] Lender directory loads.
- [ ] Lender directory filters by verified, unverified, revoked, linked Reddit, and search.
- [ ] Lender directory rows show username, reddit username, status, loan counts, and total funded.
- [ ] Lender profile opens from directory.
- [ ] Lender profile shows identity, role, reddit username, verification status, verified at/by, perm_version, created/last login.
- [ ] Lender profile stats show funded, active, repaid, unpaid, refunded, disputed, total funded, outstanding.
- [ ] Lender profile loan list renders.
- [ ] Lender profile recent loan events and audit logs render.
- [ ] Verify/revoke lender action updates UI after reload.
- [ ] Link/unlink Reddit username action updates UI after reload.
- [ ] Admin keys page loads.
- [ ] Admin-only lender directory is not visible to non-admin roles.

## Cross-Role Permission Spot Checks
- [ ] Anonymous user redirects from dashboard pages.
- [ ] Borrower cannot access `/api/admin/lenders`.
- [ ] Lender cannot access `/api/admin/lenders`.
- [ ] Mod cannot access admin lender directory/profile.
- [ ] Admin can access admin lender directory/profile.
- [ ] Borrower/lender cannot read unrelated calendar exports.
- [ ] Notification endpoint only shows current session user's notifications.

## Mobile Pass
- [ ] Borrower dashboard at phone width: no horizontal scroll.
- [ ] Lender dashboard at phone width: no horizontal scroll.
- [ ] Mod dashboard at phone width: no horizontal scroll.
- [ ] Admin lender directory at phone width: table cards are readable.
- [ ] Admin lender profile at phone width: identity, stats, loans, activity stack cleanly.
- [ ] Audit log at phone width: filters and rows remain usable.
- [ ] Global search at phone width: search box and result groups are readable.

## Launch Safety Language
- [ ] UI does not say "safe lender", "trusted lender", "credit score", "guaranteed", "collection", or "broker".
- [ ] Verification language says "Completed LoanCentral lender verification process."
- [ ] No public shame, pressure, collection, or guarantee language appears.
- [ ] Reddit queue pages remain review-only unless explicitly staged for safe manual action.

## Final Before Beta
- [ ] Run `python -m unittest discover -s tests -q`.
- [ ] Confirm reports are current: `PERMISSION_AUDIT_REPORT.md`, `SCHEMA_PARITY_REPORT.md`, `BACKUP_RESTORE.md`.
- [ ] Backup database before deploy.
- [ ] Deploy.
- [ ] Backup database after successful deploy.
- [ ] Smoke-test `testadmin`, `testmod`, `logistix1`, and `hawtchili`.
