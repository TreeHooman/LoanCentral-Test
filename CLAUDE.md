# LoanCentral — Reddit lending bot + web dashboard

Reddit bot (PRAW) that records peer-to-peer loans via `$` commands, plus a Flask
dashboard/API for lenders, borrowers, mods, and admins. Postgres in prod
(Render), SQLite for dev/tests.

## Working set (core files — start here)

| Area | Files |
|---|---|
| Bot entry | `main.py` — PRAW comment loop, auto-discovers `commands/*.py` |
| Commands | `commands/` — loan, fund, paid, unpaid, refund, dispute, logi, help, lender_gate |
| Business logic | `services.py` (~5300 lines, monolith — split post-launch) |
| Data access | `local_db.py`, `schema.sql` |
| Web/API | `api/app.py` (~3100 lines, ~147 routes), `api/auth.py`, `api/templates/` |
| Shared | `utils.py` (reddit client + rate limiter), `bot_messages.py`, `integrity.py` |
| Config | `render.yaml`, `requirements.txt`, `.env.example` |

## Load on demand (don't preload)

- `docs/reports/` — point-in-time audit/checklist reports (historical)
- `scripts/` — reminder_job, dev/test DB setup, seeds, integrity check
- `migrations/` — run from repo root: `python migrations/<script>.py`
- `tests/` — pytest suite
- `archive/` — spent one-shot scripts, history only

`backup_prod_db.py` stays at repo root — Windows Task Scheduler (daily 2AM)
references it by absolute path. Do not move it.

## Commands

```
python -m pytest tests/ -q     # full suite — must be green before commit
python run_dev.py              # SAFE dev server: forces sqlite + LOANCENTRAL_ENV=dev
                               #   → data/loancentral_dev.sqlite3, never touches prod
python main.py                 # LIVE bot — do not run without explicit user OK
```

Dev login: `/auth/dev-login`, quick lender login `/auth/dev-login-as/<username>`.

## Environment

- `.env` points at **production** Postgres (Render, Oregon). Treat as live.
- `.env.test` / `.env.dev` → local SQLite. `run_dev.py` loads these and hard-forces
  `DB_BACKEND=sqlite` so the dashboard preview can never hit prod.
- Active branch: `upgrade/tested-bot-core`.

## Security rules

See [docs/SECURITY.md](docs/SECURITY.md) — standing rules, **never violate**.
Highlights: no Reddit OAuth; DB (not Reddit flair) is the source of truth for
permissions; API keys header-only (`X-API-Key`); no live Reddit API calls
unless explicitly marked safe (queue via `enqueue_reddit_action` instead).

## Architecture notes

- Flow: Reddit comment → `main.py` loop → `commands/<cmd>.py` → `services.py` → `local_db.py`.
- Dashboard: browser → `api/app.py` route → `services.py` → DB.
- New bot commands: drop a module in `commands/` — `main.py` auto-discovers it.
- Route conflict trap: `/api/requests/*` = OLD request system; `/api/loan-requests/*`
  = NEW `loan_requests` table. Never mix them.
- Money-changing actions must write to the audit log.
