# Staging Checklist

## Current Gate

Do not use Reddit API or production credentials yet.

Before test Reddit accounts are needed, finish:

- offline tests passing
- read-only integrity check ready
- test database available
- test `.env` pointing only at the test database

## Safe Commands

Run all offline tests:

```powershell
venv\Scripts\python.exe -m unittest discover -s tests
```

Initialize schema against the test database configured in `.env.test`:

```powershell
venv\Scripts\python.exe scripts\setup_test_db.py
```

Run a read-only database integrity check against `.env.test`:

```powershell
venv\Scripts\python.exe scripts\run_integrity_check.py
```

Both scripts default to `.env.test`. They refuse database names that do not look like test, dev, stage, or staging unless explicitly overridden.

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

The phrase for moving to Reddit test setup is:

```text
Now make the test Reddit accounts/subreddit.
```

Until then, do not connect the bot to Reddit.

## Integration Order

1. Run offline tests.
2. Run integrity check on test database.
3. Create test Reddit accounts/subreddit.
4. Fill test-only credentials.
5. Run controlled staging tests.
6. Backup production database.
7. Stop old bot.
8. Deploy upgrade.
9. Run one controlled production flow.
10. Monitor logs.
