# ARCHITECTURE.md

LoanCentral is two processes sharing one database:

```
Reddit comments ──► main.py (PRAW stream loop)
                      │  auto-discovers commands/*.py
                      ▼
                 commands/<cmd>.py   (parse + permission gate)
                      ▼
                 services.py         (business logic, validation, audit)
                      ▼
                 local_db.py         (connection; Postgres prod / SQLite dev)
                      ▲
                 api/app.py          (Flask dashboard + JSON API)
                      ▲
Browser / API ────────┘
```

## Bot (`main.py`)

- Loads `.env`, builds the PRAW client from `utils.py` (shared `reddit` instance
  + `reddit_limiter` rate limiter), streams comments from `SUBREDDITS`.
- **Command auto-discovery**: every `commands/*_command.py` module exposing a
  `COMMAND_TRIGGER` and a `process_*` function is loaded automatically — adding
  a bot command means adding one file, no `main.py` edits.
- Lender-only commands (`$loan`, `$fund`, `$paid_with_id`, `$unpaid`,
  `$refund`) call `commands/lender_gate.require_verified_lender` first:
  DB `verified_lender` is the granting gate; Reddit flair is a second,
  restrictive-only gate.
- Outbound Reddit writes (bans, reminders, DMs) are **not** made live: they are
  queued in the `reddit_actions` table via `enqueue_reddit_action` for human
  review (see docs/SECURITY.md rule 4).

## Web / API (`api/`)

- `api/app.py` — single Flask app: HTML dashboards (Jinja templates in
  `api/templates/`) + JSON API under `/api/*`.
- Auth model (see docs/API_REFERENCE.md): Flask session (login) or
  `X-API-Key` header (master key). Decorators: `login_required`,
  `role_required(*roles)`, `require_auth`, `require_mod_api`,
  `require_admin_api`, `verified_lender_required`.
- `api/auth.py` — Reddit OAuth helpers, present but **not configured**
  (standing rule: no Reddit OAuth). Borrower login is OTP
  (email/SMS) with per-IP rate limiting; read-only magic links via `/view/<token>`.

## Services (`services.py`)

- The monolith (~5300 lines): all business logic, one function per operation
  (`create_loan`, `mark_repaid`, `mark_unpaid`, request CRUD, analytics,
  notifications, audit logging).
- Enforces per-record ownership even for authenticated callers (e.g.
  `mark_repaid` rejects a lender who isn't the loan's recorded lender).
- `_ensure_*` helpers create/migrate tables at runtime — the live schema can be
  ahead of `schema.sql` (see docs/DATA_MODEL.md).
- Deliberately not split before launch; post-launch plan is to split by domain
  (loans / requests / admin / auth), same for `api/app.py` routes.

## Runtime environments

| | prod | dev/test |
|---|---|---|
| DB | Render Postgres (`.env`) | SQLite `data/loancentral_dev.sqlite3` (`run_dev.py` hard-forces it) |
| Reddit | live bot (only when explicitly run) | stubs, no live calls |
| Env flag | `LOANCENTRAL_ENV=prod` (default) | `dev` → enables `/auth/dev-login*` |

- Deployed on Render (`render.yaml`). Daily 2AM prod backup:
  `backup_prod_db.py` (repo root — Task Scheduler path-pinned) → `backups/*.sql.gz`.
- Background jobs live in `scripts/` (e.g. `reminder_job.py`).
