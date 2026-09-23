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

Code: branch `refactor/dashboard-authoritative` (Render deploys `upgrade/tested-bot-core`; see E).

---

## Before launch day

### A. Where the database lives — decided: Neon  ✅

**The bot and the dashboard must use the same database.** That's what
"the database is the source of truth" means in practice: a loan funded on the
dashboard has to be the same row the bot sees.

Decided 2026-09-22: both use a **Neon** Postgres database (free tier, AWS
us-west-2, next to Render). The old Render database expired in July; Neon's
free tier does not expire.

- The dashboard (`loancentral-dashboard` on Render) already points at Neon
  through `DATABASE_URL`, and `/health` reports `"db": "ok"`.
- Neon currently holds **test data only**. On launch day the main database is
  copied from the bot computer into Neon (step 3 below), replacing it.
- The bot connects to Neon with the same `DB_*` lines as `.env` on the build
  machine (step C).
- Point any uptime monitor at `/ping`, **not** `/health`. `/health` queries the
  database, and polling it keeps Neon awake and uses up the free compute hours.

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
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | the **Neon** values, copied from `.env` on the build machine (not the old bot's) | the shared database; the old bot keeps its own |
| `LOANCENTRAL_ENV` | `prod` | turns off the developer shortcuts |
| `DASHBOARD_URL` | `https://loancentral-dashboard.onrender.com` | bot comments link to it; 2.0 refuses to start without it |
| `SECRET_KEY` | a long random string, set once, never changed | signs dashboard logins; changing it signs everyone out |
| `API_KEY` | another long random string | an emergency admin key; `changeme` or blank switches it off |
| `REQUIRE_LENDER_FLAIR` | `false` | lenders are verified in LoanCentral, not by flair |
| `REDDIT_FUNDED_FLAIR` | optional, default `FUNDED` | the flair text set on funded posts |

Leave out `DASHBOARD_CLIENT_ID` and `DASHBOARD_CLIENT_SECRET`: Reddit login
stays off. The dashboard on Render has its own copies of `DATABASE_URL`,
`SECRET_KEY`, `API_KEY`, `LOANCENTRAL_ENV` and `DASHBOARD_URL`; the bot only
needs the database to be the same one.

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

### E. Put the 2.0 dashboard on Render, and tidy its settings

Render deploys the branch `upgrade/tested-bot-core`; 2.0 is on
`refactor/dashboard-authoritative`. Until that branch is merged and pushed,
the live dashboard runs the older code. This is safe to do **before** launch
day: Neon already has every 2.0 table, and the old bot never talks to Neon.

1. Merge `refactor/dashboard-authoritative` into `upgrade/tested-bot-core` and
   push. Render redeploys; wait for **Live**, then check `/health`.
2. In Render → `loancentral-dashboard` → **Environment**:
   - `API_KEY`: replace with a long random string. It is an admin key, and the
     current value is guessable.
   - `DASHBOARD_URL`: `https://loancentral-dashboard.onrender.com`.
   - `DATABASE_URL`: after resetting the Neon password (Neon → Connect →
     Reset password), paste the new connection string here and put the new
     password in `.env` on the build machine.
3. If you use an uptime monitor, point it at `/ping`.

---

## Launch day

### 1. Close the subreddit, then stop the old bot

Stop the old bot **first** so two bots never answer the same post.

### 2. Dump the main database (on the bot computer)

The old bot is stopped, so this dump is final: nothing can be recorded after
it. It is also your safety net. With the old bot's database settings:

```
pg_dump -h localhost -U <old bot's DB_USER> -d <old bot's DB_NAME> -F c -f main_launch.dump
```

(or pgAdmin → right-click the database → Backup…, format "Custom"). Check the
file is not empty, then copy `main_launch.dump` to the build machine's
`backups\` folder. **Keep the original on the bot computer too.**

### 3. Load it into Neon and upgrade it (build machine)

One script does the old steps 3 and 4: it backs up what Neon holds now, empties
Neon, restores the dump, checks every table's row count against the dump,
applies the 16 migrations (which only **add** tables and columns), checks the
counts again, and runs the read-only integrity check.

Preview first. This changes nothing and shows the dump's row counts:

```
python scripts/load_main_db.py backups\main_launch.dump
```

Check the loan and user counts look like your data, then:

```
python scripts/load_main_db.py backups\main_launch.dump --apply --target-host <DB_HOST from .env>
```

`--target-host` must repeat `DB_HOST` exactly, so a wrong `.env` can't empty
the wrong database. Expected: two `OK every table matches the dump` lines and
`Applied 16 migration(s).` It stops at the first mismatch or error; the backup
it took is in `backups\`.

The integrity check lists odd rows. The June data had one loan where lender and
borrower were the same person. Nothing it lists stops the launch.

If a NOTICE says a unique index was not created, the old data has two loans
sharing a number (the old bot numbered loans by the second). That index is
skipped, everything else still applies, and the launch can go ahead.

Rehearsed 2026-09-22 against the June dump (551 loans, 166 users) on a local
Postgres, both dump formats. Not yet run against Neon itself; if Neon refuses
the "Emptying the target" step, stop and send me the error.

### 4. Check the dashboard sees it

Open `https://loancentral-dashboard.onrender.com/health` → `"db": "ok"`.
The dashboard reads Neon directly, so there is nothing to redeploy.

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
- the dashboard is already running on Render against Neon.

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
run it by hand now and then, or schedule it every 5 minutes on the bot
computer. In a Command Prompt, from the 2.0 folder (the path is filled in by
`%CD%`):

```
schtasks /Create /TN "LoanCentral Reddit Sync" /SC MINUTE /MO 5 /F /TR "\"python\" \"%CD%\scripts\reddit_sync_worker.py\" --live"
eddit_sync_worker.py\" --live"
```

Check it with `schtasks /Query /TN "LoanCentral Reddit Sync"`, and stop it with
`schtasks /Change /TN "LoanCentral Reddit Sync" /DISABLE`.

Only one live pass can run at a time, on any machine: a second one (a manual
run during a scheduled one, say) sees "Another live sync pass is already
running" and exits without sending anything.

### 9. Reopen the subreddit and tell lenders

A pinned post: lenders record loans on the dashboard with the request code,
Reddit commands still work, and they get their login key from a mod.

---

## If it goes wrong: rolling back

1. Stop 2.0 (bot, and dashboard if it's running).
2. Start the old bot from its untouched folder.
3. Reopen the subreddit.

**The old bot's database was never touched.** Launch copied it into Neon; the
original on the bot computer is exactly as it was at step 2. Start the old bot
against it as before.

Anything recorded in 2.0 (test loans, or real ones if you roll back later)
exists only in Neon. Before rolling back after real use, note those loans so
they can be re-entered.

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
