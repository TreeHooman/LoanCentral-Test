# Staging Checklist

## Current Gate

Current plan as of 2026-09-08: use the existing bot account and API registration
for controlled LoanCentral EU testing. A new test bot account is not required.
Keep the test database and monitoring list separate from the legacy process.
No live configuration has been changed. See [release plan](REQUEST_CODE_RELEASE.md).

Before live staging, finish:

- offline tests passing
- read-only integrity check ready
- test database available
- test `.env` pointing only at the test database
- a launcher that validates the resolved database destination and exact test
  subreddit before importing the Reddit client
- lender-only workflow tests; borrower confirmation is not required for this
  feature (owner decision, 2026-09-08)

## Safe Commands

Run all offline tests:

```powershell
python -m pytest tests/ -q
```

Initialize schema against the test database configured in `.env.test`:

```powershell
venv\Scripts\python.exe scripts\setup_test_db.py
```

Run a read-only database integrity check against `.env.test`:

```powershell
venv\Scripts\python.exe scripts\run_integrity_check.py
```

Both scripts default to `.env.test`, but their current guards also accept a
test environment flag. That does not prove the resolved database is isolated;
verify host/name and inherited environment before using them. The offline
preview in `scripts/demo_request_flow.py` forces its own SQLite destination.

Use this only after `.env.test` is filled with a real test database:

```env
DB_HOST=
DB_PORT=5432
DB_NAME=loancentral_test
DB_USER=
DB_PASSWORD=
LOANCENTRAL_ENV=test
```

## Test Reddit Gate

The legacy host is another computer, not this development machine. Confirm its
startup/restart setup, exact EU subreddit, destination database, and monitoring
lists before a live test. Preserve the existing working deployment and API
credentials. The previous new-account setup plan is superseded by the owner's
shared-account testing preference.

## Integration Order

1. Run offline tests.
2. Run integrity check on test database.
3. Prepare the isolated EU test environment using the existing bot account.
4. Confirm resolved configuration and prevent overlapping subreddit monitors.
5. Run controlled staging tests.
6. Backup production database.
7. Stop old bot.
8. Deploy upgrade.
9. Run one controlled production flow.
10. Monitor logs.
