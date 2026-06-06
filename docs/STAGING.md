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

Run a read-only database integrity check against whatever `.env` points to:

```powershell
venv\Scripts\python.exe scripts\run_integrity_check.py
```

Only run the integrity check after confirming `.env` points at a dev or staging database.

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
