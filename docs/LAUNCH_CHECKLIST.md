# LoanCentral 2.0 — Launch Checklist (owner steps)

Everything that could be done and verified on the build machine is done. What
is left needs your credentials, your production database, your Reddit account,
or a decision only you can make. Work top to bottom — each step assumes the one
above it.

Code is on branch `refactor/dashboard-authoritative`. Suite: 811 tests, run
with **system Python** (`python -m pytest tests/ -q`) — the `venv/` has no
pytest.

---

## 1. Back up the live database

```bash
python backup_prod_db.py
```

Confirm a fresh file appears in `backups/`. Do not continue without it.

## 2. Inspect a *copy* of the live database — not the live one

Restore the backup into a scratch Postgres database (docs/BACKUP_RESTORE.md),
point `DB_NAME` at the copy, then:

```bash
python scripts/check_db_integrity.py --verbose
python scripts/run_migrations.py --status
```

What to look for:

- **`loan_requests` column shape.** The dev database had legacy columns
  (`post_date NOT NULL`, `funded_by`, …) that broke request creation until
  this build. The code now adapts to whatever columns exist, but if the live
  table has *another* NOT NULL column with no default, request creation will
  still fail. Compare it against `LEGACY_DDL` in
  `tests/test_legacy_schema.py`; if it differs, add the difference there and
  rerun the tests.
- **Integrity problems.** Anything the checker lists will block validating
  the new constraints later. It never changes data; fixing rows is your call.
  (The dev copy had one self-loan, row 317.)

## 3. Apply migrations 012–014 — copy first, then live

On the copy:

```bash
ALLOW_PROD_MIGRATIONS=yes python scripts/run_migrations.py
```

Then point the dashboard at the copy and click through one funding (step 6's
flow, without the Reddit part). If it works, repeat the migration against the
live database.

All three are additive: a tracking table, constraints added `NOT VALID` (they
do not reject existing rows), retry columns, and a `banned_users` table.
Nothing is dropped or rewritten.

## 4. Configure the environment (Render + the bot machine)

| Variable | Why |
|---|---|
| `PRIMARY_SUBREDDIT` | where flair/comment syncs are posted |
| `REDDIT_FUNDED_FLAIR` | optional — flair text for funded posts, default `FUNDED` |
| `SECRET_KEY`, `API_KEY` | must be real values; `API_KEY=changeme` disables key auth |
| `LOANCENTRAL_ENV=prod` | turns off dev login |

Do **not** set `DASHBOARD_CLIENT_ID` / `DASHBOARD_CLIENT_SECRET` — Reddit
OAuth stays off by your own rule.

## 5. Give the bot the Reddit permissions sync needs

- Setting a post's flair needs the bot account to be a **moderator with the
  `flair` (or `posts`) permission** on the subreddit.
- Editing its own "Funded by" comment needs no extra permission.

Without mod rights, flair syncs will fail and land in *Bans & Reddit Sync →
needs attention*; the loans themselves are unaffected.

## 6. One live test on a test subreddit

With `SUBREDDITS` set to a test subreddit only, and the old bot stopped or
pointed elsewhere so two bots do not answer the same post:

1. `python main.py`
2. Post `[REQ] ($10) (#Test) (Repay $12) (MM/DD)` from a borrower account.
3. Confirm the bot replies with a request code.
4. On the dashboard, as a verified lender: **Record Loan** → enter the code →
   confirm.
5. `python scripts/reddit_sync_worker.py` — expect a dry run listing
   `flair_sync` and `funded_comment`.
6. `python scripts/reddit_sync_worker.py --live` — check the post shows the
   flair and the bot's comment now says "Funded by u/…".
7. Record a payment on the dashboard; confirm the loan shows repaid.

## 7. Decide how the sync worker runs

Nothing sends to Reddit unless `reddit_sync_worker.py --live` runs. Pick one:

- **Windows Task Scheduler** on the bot machine every 5–10 minutes (same
  pattern as the nightly backup), or
- a **Render cron job**, or
- run it by hand after funding sessions.

Every 5 minutes with the default limit of 25 is far inside Reddit's rate cap.

## 8. Cut over from the old bot

Stop the old bot on the other computer **before** starting bot 2.0 against
r/loancentral, so posts are not answered twice.

## 9. Tell lenders

A pinned post: lenders now record loans on the dashboard with the request
code instead of `$fund`; Reddit commands still work. Mention that verified
lender status comes from mods, not flair.

---

## Known and deliberately left

- `api/auth.py` Reddit OAuth code still exists but is unused; the login page
  no longer mentions it in production.
- `/api/requests/*` and `/api/loan-requests/*` are two route families over the
  same table. Both work; merging them is cleanup, not a launch blocker.
- `services.py` and `api/app.py` are still large single files. Splitting them
  is safe to do after launch now that the tests hit a real database.
- `ban_user` entries in the sync queue (from the older "Confirm & Ban" button)
  are still for a human to act on at Reddit; the worker does not ban on Reddit.
