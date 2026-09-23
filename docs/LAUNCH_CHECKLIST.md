# LoanCentral 2.0 — Launch Day Runbook

The plan: pick a day with a few hours free, close the subreddit, switch to
2.0, test it yourself with your own accounts, and reopen. If anything goes
wrong, switch back to the old bot.

This runbook has already been **rehearsed on this build machine** against a
restore of the June 8 backup of your LoanCentral database, on a real
PostgreSQL database, with Reddit faked. Every step below passed there
(`scripts/rehearse_launch.py`: 9/9). What can't be rehearsed here is Reddit
itself and your live data since June, and that's what your launch-day test is
for.

Code: branch `refactor/dashboard-authoritative`.

---

## Before launch day

### A. One decision: where the dashboard runs  ⚠️

**The bot and the dashboard must use the same database.** That's what
"the database is the source of truth" means in practice: a loan funded on the
dashboard has to be the same row the bot sees.

Right now they don't:

- your main database is the one the bot uses, on the bot computer;
- `render.yaml` points the dashboard at a **separate Render database**
  (`loancentral-db`), the one you said isn't the main one.

So before launch day, pick one:

| Option | What it means |
|---|---|
| **1. Dashboard on the bot computer** | Both run on the same machine against the same local database. The dashboard needs a way to be reached from the internet (for example a Cloudflare Tunnel, which you've tried before). |
| **2. Move the main database to a host both can reach** | For example Render Postgres. The bot connects to it remotely and the dashboard stays on Render. That's a one-time data move, done on launch day after the backup. |

Tell me which and I'll prepare that part too. Everything else below is the
same either way.

### B. Put the new code next to the old bot — not over it

On the bot computer, put 2.0 in a **new folder**. Leave the old bot's folder
exactly as it is: that folder *is* your rollback. Then, in the new folder:

```
pip install -r requirements.txt
```

### C. Write the new bot's settings file (the old step 4, explained)

Settings live in a text file called `.env` in the new folder. Each line is
`NAME=value`. Start by copying the old bot's `.env`: the Reddit login lines and
database lines are the same values. Then check each line below:

| Setting | What to put | Why |
|---|---|---|
| `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USERNAME`, `REDDIT_PASSWORD` | same as the old bot | the bot's Reddit login |
| `REDDIT_USER_AGENT` | `python:loancentral-bot:2.0 (by /u/YOUR_BOT_NAME)` | Reddit requires this exact shape; 2.0 refuses to start with a placeholder |
| `REDDIT_MODE` | `live` | `dry_run` means "don't touch Reddit" |
| `SUBREDDITS` | `loancentral` (no `r/`) | which subreddit the bot watches |
| `PRIMARY_SUBREDDIT` | `loancentral` | where "funded" updates are posted |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | same as the old bot | the **main** database |
| `LOANCENTRAL_ENV` | `prod` | turns off the developer shortcuts |
| `DASHBOARD_URL` | the dashboard's web address | bot comments link to it; if it's wrong, every link in every comment is wrong |
| `SECRET_KEY` | a long random string, set once, never changed | signs dashboard logins; changing it signs everyone out |
| `API_KEY` | another long random string | an emergency admin key; `changeme` or blank switches it off |
| `REQUIRE_LENDER_FLAIR` | `false` | lenders are verified in LoanCentral, not by flair |
| `REDDIT_FUNDED_FLAIR` | optional, default `FUNDED` | the flair text set on funded posts |

Leave out `DASHBOARD_CLIENT_ID` and `DASHBOARD_CLIENT_SECRET`: Reddit login
stays off. If the dashboard runs somewhere else (option 2), it needs the same
`DB_*` (or `DATABASE_URL`), `SECRET_KEY`, `API_KEY`, `LOANCENTRAL_ENV` and
`DASHBOARD_URL` values.

To make a random string: `python -c "import secrets; print(secrets.token_hex(32))"`

### D. Write down who gets which role

After the upgrade, **nobody has a role yet**: no admin, no mods, no verified
lenders. You'll set them in step 5, so decide now:

- your own username → admin
- your moderators → mod
- the lenders who hold the Verified Lender flair today → verified lender

To see everyone who has ever lent (run in the new folder once the settings
file exists; this only reads):

```
python scripts/bootstrap_roles.py --list-lenders
```

Put the verified lenders in a text file, one username per line, for example
`verified.txt`.

---

## Launch day

### 1. Close the subreddit, then stop the old bot

Stop the old bot **first** so two bots never answer the same post.

### 2. Back up the main database

This is your safety net if you need to undo more than the bot switch. With the
old bot's database settings, use `pg_dump` or `backup_prod_db.py` pointed at
the main database, and check that a new file appears.

### 3. Look before changing (reads only)

```
python scripts/run_migrations.py --status
python scripts/check_db_integrity.py
```

`--status` should list all 15 migrations as "pending". The integrity check
lists odd rows. The June data had one loan where lender and borrower were the
same person. Nothing it lists stops the launch; it just tells you what's there.

### 4. Upgrade the database (the old step 3, explained)

The old bot's database has two tables: `loans` and `users`. 2.0 also needs
tables for requests, roles, bans, audit history and so on, plus some extra
columns on `loans`. A **migration** is a small script that adds them. The 15
in `scripts/migrations/` run in order, and each one is recorded so it never
runs twice.

They only **add** things. None of them deletes, rewrites or changes an
existing loan or user, and the tests fail the build if one ever tries. The old
bot's own SQL was rehearsed against the upgraded database and still works,
which is what makes the rollback below possible.

```
set ALLOW_PROD_MIGRATIONS=yes
python scripts/run_migrations.py
```

(In PowerShell the first line is `$env:ALLOW_PROD_MIGRATIONS="yes"`.)

Expected result: `Applied 15 migration(s).` Run it again and it should say
`Database is up to date.`

If it prints a NOTICE saying a unique index was not created, the old data has
two loans sharing a number (the old bot numbered loans by the second). That
index is skipped, everything else still applies, and the launch can go ahead.

### 5. Give people their roles

Preview first. This changes nothing:

```
python scripts/bootstrap_roles.py --admin YOURNAME --mod MODNAME --lenders-file verified.txt
```

Then apply, and get your own login key:

```
python scripts/bootstrap_roles.py --admin YOURNAME --mod MODNAME --lenders-file verified.txt --apply --issue-admin-key
```

**Copy the `LC-...` key it prints.** It's shown once. Sign in to the dashboard
at `/login` with **Login with Key**. From the admin area you can then issue
keys to lenders and mods, and verify or revoke lenders later.

### 6. Start 2.0

- the bot: `python main.py`. Its first log lines should include "Database
  check finished". If they say statements were skipped, note them; the bot
  still runs.
- the dashboard, wherever you decided in A.

### 7. Test it yourself (sub still closed)

Use two accounts you control, one as lender and one as borrower, and small
amounts.

1. Borrower posts `[REQ] ($10) (#Test) (Repay $12) (MM/DD)`.
   → the bot replies once, with a request code and a dashboard link.
2. On the dashboard, as a verified lender: **Record Loan** → enter the code →
   tick the confirmation → **Record Loan**.
   → the loan appears on the lender dashboard.
3. Send the funded update to Reddit:
   ```
   python scripts/reddit_sync_worker.py          (shows what it will do)
   python scripts/reddit_sync_worker.py --live   (does it)
   ```
   → the post's flair changes to FUNDED and the bot's comment gains
   "Funded by u/…". If either fails, it shows under **Admin → Bans & Reddit
   Sync → needs attention**. The loan is recorded either way.
4. Record a repayment on the dashboard. → the loan shows repaid.
5. Optional: a Reddit command, e.g. `$paid_with_id` on a second test loan.

Then mark any test loans **Refunded** so they don't count in anyone's history.
(Nothing is ever deleted.)

### 8. Decide how Reddit updates keep flowing

Nothing is posted to Reddit unless `reddit_sync_worker.py --live` runs. Either
run it by hand now and then, or schedule it every 5–10 minutes (Windows Task
Scheduler, the same way as the nightly backup).

### 9. Reopen the subreddit and tell lenders

A pinned post: lenders record loans on the dashboard with the request code,
Reddit commands still work, and they get their login key from a mod.

---

## If it goes wrong: rolling back

1. Stop 2.0 (bot, and dashboard if it's running).
2. Start the old bot from its untouched folder.
3. Reopen the subreddit.

**You don't need to undo the database upgrade.** It only added tables and
columns, and the old bot's writes were rehearsed against the upgraded schema.
Loans recorded during your 2.0 test stay in the `loans` table, and the old bot
can see them.

Restore the step-2 backup **only** if data was actually damaged. That would
also lose anything recorded after the backup.

Then send me what went wrong: the bot's console output or `LoanCentral.log`,
the last lines of `run_migrations.py`, and anything under "needs attention".

---

## Known and left for after launch

- `/api/requests/*` and `/api/loan-requests/*` are two route families over the
  same table. Both work.
- `services.py` and `api/app.py` are large single files. Splitting them is safe
  after launch.
- `api/auth.py` (Reddit login) is unused and switched off.
- Older "Confirm & Ban" entries in the Reddit queue are for a human to act on.
  The worker never bans anyone on Reddit.
