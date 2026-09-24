"""Execute queued Reddit actions.

LoanCentral treats the database as authoritative and Reddit as a view of it.
Funding a loan commits the loan first and queues the Reddit side afterwards, so
a Reddit outage can never change loan state. This module is the other half:
draining `reddit_actions` and reporting what happened.

Standing rule (docs/SECURITY.md rule 4): outbound Reddit writes go through the
queue and are not made by accident. So this module is **dry-run by default** —
`run_once()` reports what it would do and changes nothing unless the caller
passes `live=True`, which `scripts/reddit_sync_worker.py` only does when given
an explicit flag.

Failure handling:
  - Every attempt increments `attempts` and records `last_error`.
  - Retries use exponential backoff via `next_attempt_at`; an action is not
    retried before then.
  - After MAX_ATTEMPTS the action is marked `failed` and left for a human.
  - A post that was deleted or removed is marked `skipped`, not `failed` —
    there is nothing to retry, and the loan is unaffected either way.
"""

import logging
import os
from datetime import datetime, timedelta

logger = logging.getLogger("LoanCentral.reddit_sync")

MAX_ATTEMPTS = int(os.getenv("REDDIT_SYNC_MAX_ATTEMPTS", "5"))

#: Backoff per attempt number, in minutes.
BACKOFF_MINUTES = (1, 5, 15, 60, 240)

#: Errors meaning "the thing is gone" — no retry will ever help.
_GONE_MARKERS = (
    "deleted", "removed", "not found", "404",
    "does not exist", "forbidden", "403",
)


def _backoff_for(attempts):
    index = min(max(attempts - 1, 0), len(BACKOFF_MINUTES) - 1)
    return timedelta(minutes=BACKOFF_MINUTES[index])


def _is_gone(error_text):
    lowered = str(error_text).lower()
    return any(marker in lowered for marker in _GONE_MARKERS)


def due_actions(limit=25):
    """Queued actions whose backoff has elapsed, oldest first."""
    from services import _get_db
    conn = _get_db()
    if not conn:
        return [], "Database connection failed."
    try:
        cur = conn.cursor()
        # The cutoff is a bound parameter rather than SQL NOW() on purpose.
        # next_attempt_at is written with datetime.now() (local), while SQLite
        # renders NOW() as CURRENT_TIMESTAMP (UTC). Comparing the two made
        # every backoff expire instantly anywhere the machine was not on UTC.
        # Both sides now use the same Python clock, on either backend.
        cur.execute("""
            SELECT id, action_type, target_user, loan_id, request_id,
                   subreddit, payload, attempts
            FROM reddit_actions
            WHERE status = 'queued'
              AND (next_attempt_at IS NULL OR next_attempt_at <= %s)
            ORDER BY id
            LIMIT %s
        """, (datetime.now(), limit))
        columns = ["id", "action_type", "target_user", "loan_id", "request_id",
                   "subreddit", "payload", "attempts"]
        return [dict(zip(columns, row)) for row in cur.fetchall() or []], None
    except Exception as e:
        logger.error(f"due_actions error: {e}", exc_info=True)
        return [], str(e)
    finally:
        cur.close()
        conn.close()


def record_attempt(action_id, *, success, error=None, gone=False):
    """Update one action's bookkeeping after an attempt.

    Never raises: the caller is mid-drain and one unwritable row must not stop
    the rest.
    """
    from services import _get_db, log_event
    conn = _get_db()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        if success:
            cur.execute("""
                UPDATE reddit_actions
                SET status = 'sent', attempts = attempts + 1,
                    last_error = NULL, next_attempt_at = NULL, updated_at = NOW()
                WHERE id = %s
            """, (action_id,))
        elif gone:
            cur.execute("""
                UPDATE reddit_actions
                SET status = 'skipped', attempts = attempts + 1,
                    last_error = %s, next_attempt_at = NULL, updated_at = NOW()
                WHERE id = %s
            """, (str(error)[:1000], action_id))
        else:
            cur.execute("SELECT attempts FROM reddit_actions WHERE id = %s", (action_id,))
            row = cur.fetchone()
            attempts = (row[0] or 0) + 1 if row else 1
            if attempts >= MAX_ATTEMPTS:
                cur.execute("""
                    UPDATE reddit_actions
                    SET status = 'failed', attempts = %s, last_error = %s,
                        next_attempt_at = NULL, updated_at = NOW()
                    WHERE id = %s
                """, (attempts, str(error)[:1000], action_id))
            else:
                cur.execute("""
                    UPDATE reddit_actions
                    SET attempts = %s, last_error = %s,
                        next_attempt_at = %s, updated_at = NOW()
                    WHERE id = %s
                """, (attempts, str(error)[:1000],
                      datetime.now() + _backoff_for(attempts), action_id))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"record_attempt error for action {action_id}: {e}", exc_info=True)
        return False
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


# ---------------------------------------------------------------------------
# Handlers — each returns (ok, error, gone)
# ---------------------------------------------------------------------------

def _payload(action):
    raw = action.get("payload")
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    import json
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


def _loan_already_repaid(loan_id):
    """True when the loan is repaid (by public or internal id). Errors -> False."""
    if not loan_id:
        return False
    from services import _get_db
    conn = _get_db()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("SELECT status FROM loans WHERE loan_id = %s OR CAST(id AS TEXT) = %s",
                    (str(loan_id), str(loan_id)))
        row = cur.fetchone()
        return bool(row) and row[0] == "repaid"
    except Exception:
        return False
    finally:
        conn.close()


def apply_flair_sync(action, reddit):
    data = _payload(action)
    post_id = data.get("reddit_post_id")
    flair_text = data.get("flair_text")
    from services import REPAID_FLAIR_TEXT
    if flair_text and flair_text != REPAID_FLAIR_TEXT and _loan_already_repaid(data.get("loan_id")):
        # A FUNDED change that failed and is being retried after the loan was
        # repaid: sending it now would overwrite REPAID. Done, nothing to send.
        logger.info(f"Skipping stale {flair_text!r} flair for repaid loan {data.get('loan_id')}")
        return True, None, False
    # The stored subreddit is only context for a human reading the queue: the
    # submission already knows which subreddit it belongs to, so requiring it
    # here would strand actions queued before SUBREDDITS was configured.
    if not (post_id and flair_text):
        return False, "flair_sync needs reddit_post_id and flair_text", True
    try:
        submission = reddit.submission(id=post_id)
        # Requires the `flair` mod permission. Losing it is an operational
        # problem, not a data one — the loan stays funded regardless.
        submission.mod.flair(text=flair_text)
        return True, None, False
    except Exception as e:
        return False, str(e), _is_gone(e)


def apply_status_comment(action, reddit):
    """Add a status message ("Funded by", "Repaid") to the bot's request comment.

    Edits the bot's existing comment on the post, or replies to the post when
    there isn't one (a loan recorded with $loan). Editing is preferred: it
    costs the same one API call, keeps the thread tidy, and cannot produce a
    second copy of the message if this is retried.
    """
    data = _payload(action)
    body = data.get("body")
    kind = action.get("action_type") or "status_comment"
    if not body:
        return False, f"{kind} has no body", True
    comment_id = data.get("reddit_comment_id")
    post_id = data.get("reddit_post_id")
    try:
        if comment_id:
            comment = reddit.comment(id=comment_id)
            existing = getattr(comment, "body", "") or ""
            if body in existing:
                return True, None, False      # already synced
            comment.edit(f"{existing}\n\n---\n\n{body}" if existing else body)
            return True, None, False
        if post_id:
            reddit.submission(id=post_id).reply(body)
            return True, None, False
        return False, f"{kind} needs reddit_comment_id or reddit_post_id", True
    except Exception as e:
        return False, str(e), _is_gone(e)


def apply_lender_flair(action, reddit):
    """Show a lender's rank in their flair: "Verified Lender · Gold" / "· Legacy".

    Only ever *rewrites* an existing lender flair — anyone whose current flair
    isn't the lender flair is skipped, so a rank can never hand out lender
    access (the flair is what grants it; commands/lender_gate.py). The text is
    computed now, so it reflects the rank at sending time. Two API calls: read
    the flair, set it (skipped if already right).
    """
    import os
    import tiers
    from commands.lender_gate import _flair_matches, base_flair_text

    data = _payload(action)
    name = data.get("reddit_username") or action.get("target_user")
    sub_name = action.get("subreddit") or os.getenv("PRIMARY_SUBREDDIT") \
        or (os.getenv("SUBREDDITS", "").split(",")[0].strip())
    if not (name and sub_name):
        return False, "lender_flair needs a username and a subreddit", True
    try:
        subreddit = reddit.subreddit(sub_name)
        rows = list(subreddit.flair(redditor=name) or [])
        current = rows[0] if rows else {}
        text, css = current.get("flair_text"), current.get("flair_css_class")
        template = current.get("flair_template_id")
        if not _flair_matches(text, template):
            return True, None, False            # not a flaired lender: nothing to do
        wanted = tiers.flair_text(name, base=base_flair_text())
        if (text or "").strip() == wanted:
            return True, None, False
        template_id = (os.getenv("LENDER_FLAIR_TEMPLATE_ID") or "").strip() or template
        if template_id:
            subreddit.flair.set(name, text=wanted, flair_template_id=template_id)
        else:
            subreddit.flair.set(name, text=wanted, css_class=css or "")
        return True, None, False
    except Exception as e:
        return False, str(e), _is_gone(e)


#: Kept for callers and tests that use the old name.
apply_funded_comment = apply_status_comment

HANDLERS = {
    "flair_sync": apply_flair_sync,
    "funded_comment": apply_status_comment,
    "repaid_comment": apply_status_comment,
    "lender_flair": apply_lender_flair,
}


#: pg_advisory_lock key held by a live pass ("LCsy" as an int).
_LIVE_LOCK_KEY = 0x4C437379


def _acquire_live_lock():
    """Hold a database-wide lock for one live pass. Returns (conn, acquired).

    Actions are not claimed row by row, so two live passes at once (a manual
    run during a scheduled one, or two machines) would both send the same
    comment. The advisory lock lives in Postgres, so it covers every machine
    using the database, and it is released automatically if the process dies.
    SQLite (dev and tests) has one writer anyway, so no lock is taken there.
    """
    from services import _get_db
    import utils
    conn = _get_db()
    if isinstance(conn, utils.PooledConnection):
        # The lock is released by really closing the session, so this
        # connection must not go back to the pool (utils.get_db_connection).
        conn.close()
        conn = utils.get_db_connection(pooled=False)
    if not conn or getattr(conn, "is_sqlite", False):
        return conn, True
    cur = conn.cursor()
    try:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (_LIVE_LOCK_KEY,))
        return conn, bool(cur.fetchone()[0])
    finally:
        cur.close()


def run_once(limit=25, live=False, reddit=None):
    """Drain up to `limit` due actions.

    With live=False (the default) nothing is sent and nothing is recorded; the
    return value describes what would have been attempted.

    Returns (summary_dict, error).
    """
    if not live:
        return _run_once(limit, live, reddit)
    lock_conn, acquired = _acquire_live_lock()
    try:
        if not acquired:
            return None, "Another live sync pass is already running; skipped this one."
        return _run_once(limit, live, reddit)
    finally:
        if lock_conn is not None:
            lock_conn.close()  # closing the session releases the advisory lock


def _run_once(limit, live, reddit):
    actions, error = due_actions(limit=limit)
    if error:
        return None, error

    summary = {"considered": len(actions), "sent": 0, "failed": 0,
               "skipped": 0, "unsupported": 0, "planned": [], "live": bool(live)}

    if not live:
        for action in actions:
            summary["planned"].append(
                {"id": action["id"], "action_type": action["action_type"],
                 "request_id": action["request_id"], "loan_id": action["loan_id"]})
        return summary, None

    limiter = None
    if reddit is None:
        # Only reach for the shared client when actually going live, so tests
        # and dry runs never construct one.
        from utils import reddit as shared_reddit, reddit_limiter
        reddit, limiter = shared_reddit, reddit_limiter

    for action in actions:
        handler = HANDLERS.get(action["action_type"])
        if handler is None:
            # reminder_comment / lender_dm / ban_user stay human-reviewed.
            summary["unsupported"] += 1
            continue
        if limiter is not None:
            # Every PRAW request is already gated by _ThrottledRequestor; this
            # keeps the worker from queueing up behind its own burst.
            limiter.wait()
        ok, err, gone = handler(action, reddit)
        record_attempt(action["id"], success=ok, error=err, gone=gone)
        if ok:
            summary["sent"] += 1
        elif gone:
            summary["skipped"] += 1
            logger.warning(f"Reddit action {action['id']} skipped (gone): {err}")
        else:
            summary["failed"] += 1
            logger.error(f"Reddit action {action['id']} failed: {err}")

    return summary, None


def sync_failures(limit=100):
    """Actions a human should look at — for the admin dashboard."""
    from services import _get_db
    conn = _get_db()
    if not conn:
        return [], "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, action_type, status, target_user, loan_id, request_id,
                   attempts, last_error, updated_at
            FROM reddit_actions
            WHERE status IN ('failed', 'skipped')
               OR (status = 'queued' AND attempts > 0)
            ORDER BY updated_at DESC
            LIMIT %s
        """, (limit,))
        columns = ["id", "action_type", "status", "target_user", "loan_id",
                   "request_id", "attempts", "last_error", "updated_at"]
        rows = []
        for row in cur.fetchall() or []:
            record = dict(zip(columns, row))
            if record["updated_at"]:
                record["updated_at"] = str(record["updated_at"])
            rows.append(record)
        return rows, None
    except Exception as e:
        logger.error(f"sync_failures error: {e}", exc_info=True)
        return [], str(e)
    finally:
        cur.close()
        conn.close()
