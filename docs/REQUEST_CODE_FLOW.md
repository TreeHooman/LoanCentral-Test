# Request Code Funding

The local upgrade connects a Reddit request to a dashboard loan record. It does
not transfer money. No production configuration changes are needed to preview it.

## Offline Preview

From the repository root:

```powershell
python scripts/demo_request_flow.py --port 5055
```

Each run creates a new database under `data/request_demo_<random>/`. It never
resets an existing database. The launcher forces SQLite and offline Reddit mode,
disables Reddit login, and listens only on `127.0.0.1`.

1. Open the lender login URL printed by the launcher.
2. Open its request URL, or select Record Loan and enter the printed code.
3. Review the fake borrower, CAD 150 principal, CAD 180 repayment, and due date.
4. Check the funds-sent confirmation (this is fake data) and record the loan.
5. Find the Paid ID in the lender dashboard and record a fake repayment.
6. Sign in at `/auth/dev-login-as/demo_borrower` to inspect the borrower view.

New request codes use the existing eight-character dashboard ID format. Old
numeric codes such as `3841` and `REQ-3841` still work. The code is a reference,
not a password: recording funding requires a signed-in verified lender.

Owner decision, 2026-09-08: lenders record loans and repayment updates. No
borrower confirmation or approval step is required for this workflow. Borrowers
may view their records; viewing is not a prerequisite for the lender's action.

## Current Behavior

- The bot adds a request-specific dashboard link to its usual request reply.
- The link survives login and opens the request in the lender form.
- Borrower, principal, currency, payment method, and source thread come from the
  request. Repayment amount and date remain editable for the agreed terms.
- Funding saves the loan, borrower/lender totals, request-to-loan link, and
  request funding audit event together. A failed save rolls all of them back.
- Competing funders cannot create two loans from one request.
- The existing Reddit `$fund` command accepts both old and new code formats.

## Before Reddit Testing

The production bot runs on a separate computer and its deployment settings have
not been changed. To test the upgraded process in LoanCentral EU later, first
confirm the exact subreddit name, its availability for testing, and the legacy
startup configuration. Give
each process a distinct subreddit list and use a separate test database shared
by the upgraded bot and test dashboard. The shared Reddit account still shares
API limits and account-level risk.

The offline demo is not a public deployment. Live account linking/login and
production PostgreSQL validation remain separate launch work. Dashboard funding
does not yet send a confirmation comment to Reddit; queued outbound delivery
is still separate work.

## Verification

```powershell
python -m pytest tests/test_request_funding_flow.py tests/test_fund_command.py -q
```

`tests/request_funding_browser.cjs` exercises desktop and mobile against a fresh
offline demo on port 5055. It requires Playwright and Edge and records the demo's
fake loan. Screenshots are written under `data/`.
