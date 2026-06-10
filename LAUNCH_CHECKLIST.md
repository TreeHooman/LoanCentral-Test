# Launch Checklist

LoanCentral launch readiness checklist for private beta and early operational use.

## Core Controls

- [ ] Permissions tested across borrower, lender, mod, and admin roles
- [ ] Lender-only bot commands require both DB verification and Reddit Verified Lender flair
- [ ] Verification approval and revocation tested
- [ ] Reddit username linking and unlinking tested
- [ ] Audit logging confirmed for admin moderation and verification actions

## Operations

- [ ] Audit log filters reviewed with actor, target user, loan ID, action type, and date range
- [ ] Global search reviewed for users, verified lenders, and loans
- [ ] Admin lender directory reviewed on desktop and mobile
- [ ] Admin lender profile reviewed with summary, metrics, history, and activity sections
- [ ] Verification queue reviewed for pending, approved, denied, and more-info states

## Borrower and Lender Flows

- [ ] Loan creation tested
- [ ] Repayment recording tested
- [ ] Unpaid flow tested
- [ ] Refund flow tested
- [ ] Borrower dispute flow tested
- [ ] Notifications reviewed for borrower and lender visibility
- [ ] Loan timeline reviewed
- [ ] ICS calendar export reviewed

## Data Safety

- [ ] `schema.sql` checked against current operational schema
- [ ] `SCHEMA_PARITY_REPORT.md` reviewed
- [ ] Backup procedure documented in `BACKUP_RESTORE.md`
- [ ] Restore procedure test completed and outcome documented

## Launch Boundaries

- [ ] No Reddit OAuth dependencies introduced
- [ ] No live Reddit API changes required for launch
- [ ] Database remains the source of truth for permissions
- [ ] No language implies brokering, guarantee, debt collection, or credit scoring

## Recommended Beta Launch Steps

1. Run full automated test suite.
2. Run the manual visual checklist for borrower, lender, mod, and admin accounts.
3. Spot-check dual verification on a test lender before public beta invites.
4. Confirm backup and restore steps on the current deployment target.
5. Onboard the next private beta cohort with audit logging enabled.
