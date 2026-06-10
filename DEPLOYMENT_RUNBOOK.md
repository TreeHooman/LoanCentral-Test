# LoanCentral Deployment Runbook

## Overview

LoanCentral is a Flask application deployed on Render (web service) backed by a Render PostgreSQL database in the Oregon region.

---

## Environment

| Resource | Details |
|----------|---------|
| Platform | Render |
| Region | Oregon (US West) |
| Web Service | Flask + Gunicorn |
| Database | PostgreSQL (Render managed) |
| DB Host | dpg-d8j8p4btqb8s73btjci0-a.oregon-postgres.render.com |
| DB Name | loancentral |
| DB User | loancentral_user |
| Branch | `upgrade/tested-bot-core` |

---

## Pre-Deployment Checklist

1. All tests pass: `python -m pytest tests/ -q`
2. No uncommitted changes: `git status`
3. Schema changes applied to prod (see Schema Migrations below)
4. `.env` points to prod DB (verify `DATABASE_URL`)
5. `SECRET_KEY` is set in Render environment variables

---

## Deployment Steps

### Standard Deploy

Render auto-deploys on push to the tracked branch. To trigger manually:

1. Push to `upgrade/tested-bot-core`:
   ```
   git push origin upgrade/tested-bot-core
   ```
2. Monitor the Render dashboard for build logs.
3. Verify the deploy succeeded — check the service health indicator.
4. Run a smoke test: visit `/`, `/login`, confirm no 500 errors.

### Manual Deploy via Render Dashboard

1. Open Render dashboard → select `loancentral` web service.
2. Click **Manual Deploy** → **Deploy latest commit**.
3. Watch the build log; a successful deploy ends with `==> Your service is live`.

---

## Schema Migrations

Schema migrations are applied **manually** before deploying code that requires them.

### Steps

1. Connect to prod DB:
   ```
   psql postgresql://loancentral_user:<PASSWORD>@dpg-d8j8p4btqb8s73btjci0-a.oregon-postgres.render.com/loancentral
   ```
2. Review `schema.sql` for any new `CREATE TABLE IF NOT EXISTS` or `CREATE INDEX IF NOT EXISTS` statements since the last deploy.
3. Run only the new statements (they are idempotent by design — safe to re-run).
4. Verify tables exist: `\dt`

### Tables Added Per Sprint

| Sprint | Tables Added |
|--------|-------------|
| 8 | `notification_preferences`, `feedback_submissions`, `analytics_events` |
| 10 | `announcements` |

---

## Rollback

### Application Rollback

1. In Render dashboard, go to the web service → **Deploys** tab.
2. Find the last known-good deploy.
3. Click **Redeploy** on that commit.

### Database Rollback

There are no destructive migrations (all use `CREATE IF NOT EXISTS`). No schema rollback is needed for typical deploys. If a bad migration ran:

1. Connect to prod DB via psql.
2. Manually `DROP` or `ALTER` the affected table/column.
3. Redeploy the previous application version.

---

## Backup

Render PostgreSQL includes daily automated backups (retained 7 days on free tier, longer on paid plans).

### Manual Backup Before Risky Changes

```
pg_dump postgresql://loancentral_user:<PASSWORD>@dpg-d8j8p4btqb8s73btjci0-a.oregon-postgres.render.com/loancentral > backup_$(date +%Y%m%d).sql
```

Store the dump somewhere safe (not in the repo).

### Restore From Backup

```
psql postgresql://loancentral_user:<PASSWORD>@dpg-d8j8p4btqb8s73btjci0-a.oregon-postgres.render.com/loancentral < backup_YYYYMMDD.sql
```

---

## Environment Variables (Render)

The following env vars must be set in Render's environment configuration:

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | Full PostgreSQL connection string |
| `SECRET_KEY` | Flask session secret (long random string) |
| `FLASK_ENV` | `production` |
| `BOT_API_KEY` | Bot-to-dashboard API key |

Never commit these to the repository.

---

## Health Checks

| Check | URL |
|-------|-----|
| App running | `GET /` — expect 200 or 302 |
| Login page | `GET /login` — expect 200 |
| Stats API | `GET /api/stats` with valid session — expect 200 JSON |
| Admin metrics | `GET /api/admin/metrics` with mod session |

---

## Common Issues

### 500 on all routes after deploy

- Check Render build logs for import errors.
- Verify `DATABASE_URL` is set correctly in Render env.
- Check if a new table is missing: connect to DB and run `\dt`.

### Login OTP not arriving

- Verify `contact_email` / `contact_phone` is set for the user in the `user_roles` table.
- Check that the email/SMS provider credentials are set in env vars.

### Bot not recording loans

- Verify `BOT_API_KEY` matches the key the bot is using.
- Check `/api/activity` for recent bot events.
- Review the bot's own logs.

---

## Post-Deploy Verification

1. Log in as admin — confirm dashboard loads.
2. Check `/api/admin/metrics` returns data.
3. Confirm `/admin/health` community health page renders.
4. Verify announcements banner appears/dismisses correctly.
5. Check audit log for any unexpected errors.
