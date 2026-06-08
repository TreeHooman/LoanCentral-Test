# LoanCentral Deployment Checklist

## Before Deploy

- Confirm you are on the tested upgrade branch.
- Confirm `.env` contains production values only on the server, never in Git.
- Backup the production database.
- Save the current production commit hash for rollback.
- Stop the old bot process.

## Database

- Run read-only integrity checks first.
- Run `scripts/migrations/001_dashboard_columns.sql` on the production database.
- Re-run integrity checks after migration.
- Confirm existing loans still load.

## App And Bot

- Install dependencies in the production virtual environment.
- Start the Flask dashboard with production environment variables.
- Start the Reddit bot with production credentials only after offline and staging checks pass.
- Confirm the bot can read commands but does not duplicate old replies.

## Smoke Test

- Log in as a mod.
- Log in as a lender.
- Log in as a borrower.
- Open lender dashboard and export CSV.
- Open borrower dashboard and profile page.
- Record one controlled test loan on the agreed live test thread.
- Mark one controlled repayment.
- Confirm stats and loan history update correctly.

## Monitoring

- Watch Flask logs.
- Watch bot logs.
- Watch database errors.
- Keep rollback files and database backup available.

## Rollback

- Stop dashboard and bot.
- Restore previous commit.
- Restore database backup only if the migration or data changed incorrectly.
- Restart old bot.
- Record what failed before trying again.
