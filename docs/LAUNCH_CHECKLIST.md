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

Code: branch `refactor/dashboard-authoritative` (Render deploys `upgrade/tested-bot-core`; see F).

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
- In Neon → project → **Computes** → edit the primary compute, set the
  autoscaling **maximum to 0.25 CU**. The free plan allows 100 compute-hours a
  month; at the default maximum of 2 CU a busy hour costs 8× as much. Check
  **Usage** on the Neon dashboard once a week after launch.
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
| `SUBREDDITS` | `loancentral` (no `r/`) | which subreddit the bot watches. Only `loancentral`: remove `LoanCentralEU` if the old bot computer's .env still lists it |
| `PRIMARY_SUBREDDIT` | `loancentral` | where "funded" updates are posted |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | the **Neon** values, copied from `.env` on the build machine (not the old bot's) | the shared database; the old bot keeps its own |
| `LOANCENTRAL_ENV` | `prod` | turns off the developer shortcuts |
| `DASHBOARD_URL` | `https://loancentral.net` | bot comments link to it; 2.0 refuses to start without it |
| `SECRET_KEY` | a long random string, set once, never changed | signs dashboard logins; changing it signs everyone out |
| `API_KEY` | another long random string | an emergency admin key; `changeme` or blank switches it off |
| `LENDER_FLAIR_TEXT` | `Verified Lender` (the default) | the flair that grants lender commands; exact text, commas for several |
| `LENDER_FLAIR_TEMPLATE_ID` | optional: the lender flair template's ID | when set, only that mod-only template counts, not the text |
| `REDDIT_SYNC_IN_BOT` | `true` | after each command the bot sends queued Reddit updates (funded flair and comment) straight away, instead of waiting for step 8's schedule. Leave it out to keep Reddit updates manual |
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
- verified lenders: **nothing to list.** Anyone with the lender flair is
  let into lender commands and recorded as verified the first time they use
  one. Only list lenders who should use the **dashboard** before they've used
  the bot.

To see everyone who has ever lent (run in the new folder once the settings
file exists; this only reads):

```
python scripts/bootstrap_roles.py --list-lenders
```

Put the verified lenders in a text file, one username per line, for example
`verified.txt`.

### E. Lock down the lender flair (Reddit)

The lender flair now grants lender commands, so check in the subreddit's mod
tools → **User flair**:

- the lender flair template is **mod only** (users can't pick it);
- **"Allow users to assign their own flair"** is off, or at least no template
  lets users type free text (otherwise anyone could type "Verified Lender").

Optionally copy the template's ID into `LENDER_FLAIR_TEMPLATE_ID` (step C) so
only that template counts. The bot must also stay a **moderator with the
flair permission** (it sets FUNDED/REPAID flair).

### G. Custom domain and Google sign-in (one-time)

**Domain: loancentral.net.** In Render → `loancentral-dashboard` → Settings →
**Custom Domains** → add `loancentral.net` (and `www.loancentral.net`). Render
shows the DNS records to create at your domain registrar; HTTPS is automatic
once they resolve. The old `onrender.com` address keeps working.

**Google sign-in.** Everyone signs in with Google after proving their Reddit
name once with `$login` (the bot DMs them a setup link).

1. Google Cloud Console → create a project → **APIs & Services → OAuth consent
   screen**: External; app name LoanCentral; your email; scopes `openid` and
   `email` only (no review needed for these). Publish it.
2. **Credentials → Create credentials → OAuth client ID** → Web application.
   Authorized redirect URI: `https://loancentral.net/auth/google/callback`.
3. Put the client ID and secret into Render as `GOOGLE_CLIENT_ID` and
   `GOOGLE_CLIENT_SECRET`.
4. Test: comment `$login`, open the DM link, Continue with Google; sign out;
   Sign in with Google.

The bot's Reddit account must be able to send DMs: an established account with
some karma, not brand new (Reddit filters link DMs from new accounts).

### F. Put the 2.0 dashboard on Render, and tidy its settings

Render deploys the branch `upgrade/tested-bot-core`; 2.0 is on
`refactor/dashboard-authoritative`. Until that branch is merged and pushed,
the live dashboard runs the older code. **Decided: deploy on launch day**, right
after step 3 (the bot computer's Reddit settings are needed for the bot anyway).

Done 2026-09-23: `API_KEY` replaced (old one rejected), Neon compute capped at
0.25 CU. Still to do: step 1 below, on launch day.

1. Merge `refactor/dashboard-authoritative` into `upgrade/tested-bot-core` and
   push. Render redeploys; wait for **Live**, then check `/health`.
2. In Render → `loancentral-dashboard` → **Environment**:
   - `API_KEY`: replace with a long random string. It is an admin key, and the
     current value is guessable.
   - `DASHBOARD_URL`: `https://loancentral.net`.
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

Open `https://loancentral.net/health` → `"db": "ok"`.
The dashboard reads Neon directly, so there is nothing to redeploy.

### 5. Give people their roles

Your Reddit account is **`embarrassed-throat42` (two r's)**, the name the old
bot's records already use (15 loans). Use exactly that spelling below. (The
pre-launch admin account was typed as `embarassed-throat42`, one r; launch day
replaces the database, so that account goes away and this recreates yours.)

Preview the roles. This changes nothing:

```
python scripts/bootstrap_roles.py --admin embarrassed-throat42 --mod left-associate3911 --mod logistix1 --lender embarrassed-throat42 --lender left-associate3911 --lender logistix1 --lenders-file verified.txt
```

Then apply, and set your own admin key (you type it at a hidden prompt):

```
python scripts/bootstrap_roles.py --admin embarrassed-throat42 --mod left-associate3911 --mod logistix1 --lender embarrassed-throat42 --lender left-associate3911 --lender logistix1 --lenders-file verified.txt --apply --set-admin-key
```

Mods (decided 2026-09-25): **u/left-associate3911** and **u/logistix1**, plus you
as admin. All three are lenders too (`--lender`), so their lender commands and
dashboard work whatever their flair says.

Then give **everyone who has ever lent** a lender dashboard and a login key.
Roles set above are kept (a mod stays a mod); nobody is verified by this, and
anyone who already has a key (you, after `--set-admin-key`) is skipped. Preview
first, then add `--apply`. The keys go into the CSV file only, never on screen:

```
python scripts/bootstrap_roles.py --all-lenders --mod left-associate3911 --mod logistix1 --lender-keys-file lender_keys.csv
python scripts/bootstrap_roles.py --all-lenders --mod left-associate3911 --mod logistix1 --lender-keys-file lender_keys.csv --apply
```

Give each lender **only their own** key (Reddit DM from you), then delete
`lender_keys.csv`. A key signs in as that lender; don't share the file.

Then grant **Legacy Lender** to the founders, the same three:
**embarrassed-throat42, left-associate3911, logistix1**. Admin > Lenders > open
each one > Grant Legacy Lender.

**Required: merge the misspellings of your name.** The records hold loans under
**embarassed-throat42** and **embarrassedthroat-42** (typos). The real name is
**embarrassed-throat42 (two r's)**. Run these after step 3 and before the role
commands above (preview first without `--apply`; the latest data on the hosted
PC may have more rows than the June copy):

```
python scripts/rename_reddit_user.py embarassed-throat42 embarrassed-throat42 --apply
python scripts/rename_reddit_user.py embarrassedthroat-42 embarrassed-throat42 --apply
```

Sign in to the dashboard at `/login` with **Login with Key** and the key you
just typed (or, once you have run `!login`, with Google). From the admin area you can then issue
keys to lenders and mods, and verify or revoke lenders later.

### 6. Start 2.0

- the bot, from the 2.0 folder: `python scripts\run_bot_forever.py`. It
  starts `main.py` and starts it again if it crashes **or freezes** (no
  heartbeat for 15 minutes), after 30 seconds, waiting longer each time if it
  keeps failing straight away. A second copy refuses to start. Its first log
  lines should include "Database check finished". If they say statements were
  skipped, note them; the bot still runs. What the supervisor did is in
  `bot_supervisor.log`; the bot's own log is `LoanCentral.log`.
- **make it restart by itself** (once, from the 2.0 folder, in PowerShell):

  ```
  powershell -ExecutionPolicy Bypass -File scripts\install_bot_task.ps1
  ```

  This adds the "LoanCentral Bot" task: it starts the bot, without a window,
  at every Windows sign-in, and brings it back within 5 minutes if it is ever
  closed. If you started the bot by hand above, close that window first (the
  task takes over). Then:
  - check it: `python scripts\run_bot_forever.py --status`
  - stop it (and keep it stopped): `python scripts\run_bot_forever.py --stop`
  - start it again: `python scripts\run_bot_forever.py --start`
  - remove the task: add `-Uninstall` to the install command

  Also on the bot computer: never sleep while plugged in
  (`powercfg /change standby-timeout-ac 0`), and after a reboot Windows has to
  sign in for the task to run (automatic sign-in, or sign in yourself).
  **Never set it up on the old bot's folder.**
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
run it by hand now and then, or schedule it every **60 minutes** on the bot
computer. In a Command Prompt, from the 2.0 folder (the path is filled in by
`%CD%`):

```
schtasks /Create /TN "LoanCentral Reddit Sync" /SC MINUTE /MO 60 /F /TR "\"python\" \"%CD%\scripts\reddit_sync_worker.py\" --live"
```

Check it with `schtasks /Query /TN "LoanCentral Reddit Sync"`, and stop it with
`schtasks /Change /TN "LoanCentral Reddit Sync" /DISABLE`.

**Why hourly and not every 5 minutes:** Neon's free plan gives 100 compute-hours a month and
sleeps after 5 idle minutes. Every run wakes it, so a 5-minute schedule keeps it
awake around the clock (~180 hours) and Neon **suspends the database for the rest
of the month** when the allowance runs out, taking the bot and dashboard down.
Every 30 minutes costs about 30 hours; every 60 minutes about 15. With the
instant updates below switched on, this schedule is only a backstop for updates
that failed, so hourly is enough (decided 2026-09-25). Without them, funded
flair and comments can lag by up to an hour; the loan itself is recorded instantly. Run the worker by hand
when you want an update out sooner.

With `REDDIT_SYNC_IN_BOT=true` (step C), updates from Reddit commands such as
`$fund` go out within seconds.

**Dashboard fundings and repayments within seconds too:** on Render, set
`REDDIT_SYNC_IN_DASHBOARD` = `true`, and make sure `REDDIT_CLIENT_ID`,
`REDDIT_CLIENT_SECRET`, `REDDIT_USERNAME` (`loancentral`) and `REDDIT_PASSWORD`
hold the bot account's login (the same values as the bot computer's `.env`).
The website then posts the FUNDED / REPAID update right after the loan is saved,
while the database is awake anyway, so it costs no extra Neon compute. Do this
only **after** the real data is loaded (step 6): before that, the dashboard
holds test loans tied to real Reddit threads. Keep the hourly schedule as a
backstop for anything that fails.

Only one live pass can run at a time, on any machine: a second one (a manual
run during a scheduled one, say) sees "Another live sync pass is already
running" and exits without sending anything.

### 9. Reopen the subreddit and tell lenders

Follow [LAUNCH_PLAN.md](LAUNCH_PLAN.md) "0:50 — Go live": community type back
to Public, the launch post (draft C) stickied with the FAQ comment (draft D),
and the sidebar/wiki text (draft F). Everyone sets up their account with
`!login` (no keys to hand out); lender keys stay as a backup.

---

## If it goes wrong: rolling back

1. Stop 2.0: `python scripts\run_bot_forever.py --stop` (it stays stopped,
   even with the task installed), then remove the task:
   `powershell -ExecutionPolicy Bypass -File scripts\install_bot_task.ps1 -Uninstall`.
   Also disable the sync task:
   `schtasks /Change /TN "LoanCentral Reddit Sync" /DISABLE`.
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
