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

- Loads `.env`, builds the PRAW client from `utils.py` (shared `reddit`
  instance), streams comments from `SUBREDDITS`.
- **Reddit free-tier budget**: every outgoing HTTP request PRAW makes (stream
  polls, flair reads, replies, DMs, token refreshes) is gated through
  `reddit_limiter` by `_ThrottledRequestor` in `utils.py` — a hard 80/min cap
  under Reddit's 100 requests/min free tier. No call site can bypass it, so new
  commands need no rate-limit code. Guarded by `tests/test_reddit_rate_limit.py`.
- **Command auto-discovery**: every `commands/*_command.py` module exposing a
  `COMMAND_TRIGGER` and a `process_*` function is loaded automatically — adding
  a bot command means adding one file, no `main.py` edits.
- Lender-only commands (`$loan`, `$fund`, `$paid_with_id`, `$unpaid`,
  `$refund`) call `commands/lender_gate.require_verified_lender` first.
  The subreddit's lender flair grants them (owner decision 2026-09-23, see
  SECURITY.md rule 2): the flair is read from the comment itself (no API
  call), a flaired commenter is recorded as verified in the DB on first use
  (audited), and anyone without it is ignored silently. If the flair can't be
  read at all, the DB `verified_lender` record decides instead.
- **Identity**: the bot only ever knows a Reddit handle, while `user_roles` is
  keyed on the dashboard username and links the two via `reddit_username`.
  All bot-side permission and loan lookups go through
  `services.resolve_user_identity` / `account_aliases`, which match either name.
  Run `scripts/check_identity_links.py` to report accounts whose two names have
  drifted apart.
- Outbound Reddit writes (bans, reminders, DMs) are **not** made live from the
  bot: they are queued in `reddit_actions` via `enqueue_reddit_action`
  (see docs/SECURITY.md rule 4).
- Funding a request queues a `flair_sync` and a `funded_comment`, **after** the
  loan commits. `reddit_sync.py` executes them, but only when
  `scripts/reddit_sync_worker.py` is run with `--live`; it is dry-run by
  default. Failures retry with backoff, then land in `failed` for review at
  `/api/admin/reddit-sync/failures`. A deleted post is `skipped`, not retried.
- The bot stores its own reply's comment id on the request, so the funding
  sync **edits** that comment instead of adding a second one.

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

## Loan lifecycle (`loan_states.py`)

One module, no project imports: the allowed loan and request statuses and the
transitions between them, plus `loan_transition_error()` /
`request_transition_error()`. Every mutation consults it, so a status rule
changes in exactly one place and neither interface can invent an illegal move.
`funded` is terminal for a request — reopening one needs an admin override,
which is what prevented the same request being funded twice.

## Reddit synchronisation (`reddit_sync.py`)

Reddit is treated as a view of the database, never a source of truth. The
database is authoritative: if the dashboard says funded, it is funded, and a
Reddit outage is a queue backlog rather than a data problem.

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
