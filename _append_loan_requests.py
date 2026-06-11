"""Append Loan Request Sprint service functions to services.py."""
import os

APPEND = r'''

# ---------------------------------------------------------------------------
# Loan Request Sprint — loan_requests table, CRUD, analytics, expiration
# ---------------------------------------------------------------------------

import re as _lr_re
import random as _lr_random
import string as _lr_string

_LR_STATUSES = {
    "open", "funded", "cancelled", "expired",
    "removed", "duplicate", "denied_by_mod",
}


def _generate_request_id() -> str:
    chars = _lr_string.ascii_uppercase + _lr_string.digits
    return "REQ-" + "".join(_lr_random.choices(chars, k=8))


def _ensure_loan_requests_table(conn):
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS loan_requests (
                id                          SERIAL       PRIMARY KEY,
                request_id                  VARCHAR(20)  NOT NULL UNIQUE,
                borrower_username           VARCHAR(100) NOT NULL,
                reddit_username             VARCHAR(100),
                requested_amount            NUMERIC(12,2),
                requested_repayment_amount  NUMERIC(12,2),
                requested_due_date          DATE,
                request_status              VARCHAR(30)  NOT NULL DEFAULT 'open',
                thread_url                  TEXT,
                reddit_post_id              VARCHAR(30),
                reddit_comment_id           VARCHAR(30),
                created_at                  TIMESTAMP    NOT NULL DEFAULT NOW(),
                updated_at                  TIMESTAMP    NOT NULL DEFAULT NOW(),
                funded_loan_id              INTEGER      REFERENCES loans(id) ON DELETE SET NULL,
                notes                       TEXT
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_lr_borrower ON loan_requests (lower(borrower_username))")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_lr_status   ON loan_requests (request_status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_lr_created  ON loan_requests (created_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_lr_reddit   ON loan_requests (reddit_post_id) WHERE reddit_post_id IS NOT NULL")
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        cur.close()


def create_loan_request(
    borrower_username: str,
    reddit_username: str = None,
    thread_url: str = None,
    reddit_post_id: str = None,
    reddit_comment_id: str = None,
    requested_amount=None,
    requested_repayment_amount=None,
    requested_due_date=None,
    notes: str = None,
):
    """
    Record a new loan request. Parsing failures are allowed — missing fields
    are stored as NULL. Returns (request_id, error).
    """
    if not borrower_username:
        return None, "borrower_username is required"
    conn = _get_db()
    if not conn:
        return None, "Database connection failed"
    try:
        _ensure_loan_requests_table(conn)
        request_id = _generate_request_id()
        # Ensure uniqueness
        cur = conn.cursor()
        for _ in range(5):
            cur.execute("SELECT 1 FROM loan_requests WHERE request_id = %s", (request_id,))
            if not cur.fetchone():
                break
            request_id = _generate_request_id()

        cur.execute("""
            INSERT INTO loan_requests
              (request_id, borrower_username, reddit_username, thread_url,
               reddit_post_id, reddit_comment_id, requested_amount,
               requested_repayment_amount, requested_due_date, notes,
               request_status)
            VALUES (%s, lower(%s), %s, %s, %s, %s, %s, %s, %s, %s, 'open')
            RETURNING id
        """, (
            request_id,
            borrower_username,
            reddit_username,
            thread_url,
            reddit_post_id,
            reddit_comment_id,
            requested_amount,
            requested_repayment_amount,
            requested_due_date,
            notes,
        ))
        db_id = cur.fetchone()[0]
        conn.commit()
        log_event("loan_request_created", target_user=borrower_username.lower(),
                  source="system",
                  details={"request_id": request_id, "db_id": db_id,
                           "amount": str(requested_amount) if requested_amount else None})
        cur.close()
        return request_id, None
    except Exception as e:
        conn.rollback()
        return None, str(e)
    finally:
        conn.close()


def get_loan_request(request_id: str):
    """Fetch a single loan request by its REQ-... ID. Returns (request_dict, error)."""
    conn = _get_db()
    if not conn:
        return None, "Database connection failed"
    try:
        _ensure_loan_requests_table(conn)
        cur = conn.cursor()
        cur.execute("""
            SELECT lr.id, lr.request_id, lr.borrower_username, lr.reddit_username,
                   lr.requested_amount, lr.requested_repayment_amount,
                   lr.requested_due_date, lr.request_status, lr.thread_url,
                   lr.reddit_post_id, lr.reddit_comment_id,
                   lr.created_at, lr.updated_at, lr.funded_loan_id, lr.notes,
                   l.loan_id AS funded_loan_ref
            FROM loan_requests lr
            LEFT JOIN loans l ON l.id = lr.funded_loan_id
            WHERE lr.request_id = %s
        """, (request_id,))
        row = cur.fetchone()
        if not row:
            return None, "Request not found"
        cols = ["id","request_id","borrower_username","reddit_username",
                "requested_amount","requested_repayment_amount","requested_due_date",
                "request_status","thread_url","reddit_post_id","reddit_comment_id",
                "created_at","updated_at","funded_loan_id","notes","funded_loan_ref"]
        d = dict(zip(cols, row))
        for k in ("created_at","updated_at","requested_due_date"):
            if d[k]: d[k] = str(d[k])
        if d["requested_amount"]: d["requested_amount"] = float(d["requested_amount"])
        if d["requested_repayment_amount"]: d["requested_repayment_amount"] = float(d["requested_repayment_amount"])
        return d, None
    except Exception as e:
        return None, str(e)
    finally:
        cur.close()
        conn.close()


def get_loan_requests_for_borrower(username: str, limit: int = 100, offset: int = 0):
    """Return all loan requests for a specific borrower. Returns (requests, total, error)."""
    conn = _get_db()
    if not conn:
        return [], 0, "Database connection failed"
    try:
        _ensure_loan_requests_table(conn)
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM loan_requests WHERE lower(borrower_username) = lower(%s)",
            (username,))
        total = cur.fetchone()[0]
        cur.execute("""
            SELECT lr.id, lr.request_id, lr.requested_amount, lr.request_status,
                   lr.thread_url, lr.created_at, lr.requested_due_date,
                   l.loan_id AS funded_loan_ref
            FROM loan_requests lr
            LEFT JOIN loans l ON l.id = lr.funded_loan_id
            WHERE lower(lr.borrower_username) = lower(%s)
            ORDER BY lr.created_at DESC
            LIMIT %s OFFSET %s
        """, (username, limit, offset))
        cols = ["id","request_id","requested_amount","request_status",
                "thread_url","created_at","requested_due_date","funded_loan_ref"]
        rows = []
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            for k in ("created_at","requested_due_date"):
                if d[k]: d[k] = str(d[k])
            if d["requested_amount"]: d["requested_amount"] = float(d["requested_amount"])
            rows.append(d)
        return rows, total, None
    except Exception as e:
        return [], 0, str(e)
    finally:
        cur.close()
        conn.close()


def get_loan_request_queue(
    status: str = None,
    borrower: str = None,
    date_from: str = None,
    date_to: str = None,
    amount_min=None,
    amount_max=None,
    limit: int = 200,
    offset: int = 0,
):
    """Return loan requests with optional filters for the mod queue. Returns (rows, total, error)."""
    conn = _get_db()
    if not conn:
        return [], 0, "Database connection failed"
    try:
        _ensure_loan_requests_table(conn)
        cur = conn.cursor()
        conditions, params = [], []
        if status:
            conditions.append("lr.request_status = %s"); params.append(status)
        if borrower:
            conditions.append("lower(lr.borrower_username) LIKE lower(%s)")
            params.append(f"%{borrower}%")
        if date_from:
            conditions.append("lr.created_at::date >= %s"); params.append(date_from)
        if date_to:
            conditions.append("lr.created_at::date <= %s"); params.append(date_to)
        if amount_min is not None:
            conditions.append("lr.requested_amount >= %s"); params.append(amount_min)
        if amount_max is not None:
            conditions.append("lr.requested_amount <= %s"); params.append(amount_max)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        cur.execute(f"SELECT COUNT(*) FROM loan_requests lr {where}", params)
        total = cur.fetchone()[0]

        cur.execute(f"""
            SELECT lr.id, lr.request_id, lr.borrower_username, lr.reddit_username,
                   lr.requested_amount, lr.request_status, lr.thread_url,
                   lr.created_at, lr.requested_due_date,
                   l.loan_id AS funded_loan_ref
            FROM loan_requests lr
            LEFT JOIN loans l ON l.id = lr.funded_loan_id
            {where}
            ORDER BY
              CASE lr.request_status WHEN 'open' THEN 0 ELSE 1 END,
              lr.created_at DESC
            LIMIT %s OFFSET %s
        """, params + [limit, offset])
        cols = ["id","request_id","borrower_username","reddit_username",
                "requested_amount","request_status","thread_url",
                "created_at","requested_due_date","funded_loan_ref"]
        rows = []
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            for k in ("created_at","requested_due_date"):
                if d[k]: d[k] = str(d[k])
            if d["requested_amount"]: d["requested_amount"] = float(d["requested_amount"])
            rows.append(d)
        return rows, total, None
    except Exception as e:
        return [], 0, str(e)
    finally:
        cur.close()
        conn.close()


def update_request_status(request_id: str, new_status: str, actor: str, note: str = None):
    """
    Update a loan request's status. Mod/admin only via API layer.
    Returns (ok, error).
    """
    if new_status not in _LR_STATUSES:
        return False, f"Invalid status: {new_status}"
    conn = _get_db()
    if not conn:
        return False, "Database connection failed"
    try:
        _ensure_loan_requests_table(conn)
        cur = conn.cursor()
        update_note = f"Status changed to '{new_status}' by {actor}"
        if note:
            update_note += f": {note}"
        cur.execute("""
            UPDATE loan_requests
            SET request_status = %s,
                updated_at     = NOW(),
                notes = CASE WHEN notes IS NULL THEN %s
                             ELSE notes || E'\\n' || %s END
            WHERE request_id = %s
            RETURNING id
        """, (new_status, update_note, update_note, request_id))
        if not cur.fetchone():
            conn.rollback()
            return False, "Request not found"
        conn.commit()
        log_event("loan_request_status_updated", target_user=actor, source="system",
                  details={"request_id": request_id, "new_status": new_status})
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        cur.close()
        conn.close()


def link_request_to_loan(request_id: str, loan_db_id: int, actor: str, override: bool = False):
    """
    Link a loan request to a funded loan and mark it funded.
    Blocks if already linked unless override=True. Returns (ok, error).
    """
    conn = _get_db()
    if not conn:
        return False, "Database connection failed"
    try:
        _ensure_loan_requests_table(conn)
        cur = conn.cursor()
        cur.execute(
            "SELECT id, request_status, funded_loan_id FROM loan_requests WHERE request_id = %s",
            (request_id,))
        row = cur.fetchone()
        if not row:
            return False, "Request not found"
        _, current_status, existing_loan_id = row
        if existing_loan_id and not override:
            return False, f"Request already linked to loan ID {existing_loan_id}. Use override=True to re-link."
        cur.execute("""
            UPDATE loan_requests
            SET funded_loan_id  = %s,
                request_status  = 'funded',
                updated_at      = NOW()
            WHERE request_id = %s
        """, (loan_db_id, request_id))
        conn.commit()
        log_event("loan_request_linked", target_user=actor, source="system",
                  details={"request_id": request_id, "loan_db_id": loan_db_id,
                           "override": override})
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        cur.close()
        conn.close()


def get_request_analytics():
    """
    Return aggregate analytics for loan requests.
    Returns (stats_dict, error).
    """
    conn = _get_db()
    if not conn:
        return None, "Database connection failed"
    try:
        _ensure_loan_requests_table(conn)
        cur = conn.cursor()
        cur.execute("""
            SELECT
                COUNT(*)                                                     AS total,
                COUNT(*) FILTER (WHERE request_status = 'open')             AS open,
                COUNT(*) FILTER (WHERE request_status = 'funded')           AS funded,
                COUNT(*) FILTER (WHERE request_status NOT IN ('funded','cancelled','removed','duplicate','denied_by_mod','expired'))
                                                                             AS unfunded_active,
                COUNT(*) FILTER (WHERE request_status IN ('cancelled','removed','duplicate','denied_by_mod','expired'))
                                                                             AS closed_unfunded,
                ROUND(AVG(requested_amount) FILTER (WHERE requested_amount IS NOT NULL), 2)
                                                                             AS avg_requested,
                ROUND(AVG(requested_amount) FILTER (WHERE request_status = 'funded' AND requested_amount IS NOT NULL), 2)
                                                                             AS avg_funded_amount,
                ROUND(
                  100.0 * COUNT(*) FILTER (WHERE request_status = 'funded')
                  / NULLIF(COUNT(*), 0), 1
                )                                                            AS funding_rate_pct
            FROM loan_requests
        """)
        row = cur.fetchone()
        cols = ["total","open","funded","unfunded_active","closed_unfunded",
                "avg_requested","avg_funded_amount","funding_rate_pct"]
        stats = dict(zip(cols, row))
        for k in stats:
            if stats[k] is not None:
                stats[k] = float(stats[k]) if isinstance(stats[k], __builtins__.__class__) else stats[k]
            if stats[k] is not None:
                try: stats[k] = float(stats[k])
                except (TypeError, ValueError): pass

        # Weekly breakdown (last 8 weeks)
        cur.execute("""
            SELECT
                date_trunc('week', created_at)::date AS week_start,
                COUNT(*)                              AS requests,
                COUNT(*) FILTER (WHERE request_status = 'funded') AS funded
            FROM loan_requests
            WHERE created_at >= NOW() - INTERVAL '8 weeks'
            GROUP BY 1 ORDER BY 1 DESC
        """)
        weekly = [{"week": str(r[0]), "requests": r[1], "funded": r[2]}
                  for r in cur.fetchall()]
        stats["weekly"] = weekly
        return stats, None
    except Exception as e:
        return None, str(e)
    finally:
        cur.close()
        conn.close()


def expire_old_requests(days: int = 10, dry_run: bool = False):
    """
    Mark open requests older than `days` days as expired.
    Never deletes. Returns (expired_count, error).
    """
    conn = _get_db()
    if not conn:
        return 0, "Database connection failed"
    try:
        _ensure_loan_requests_table(conn)
        cur = conn.cursor()
        if dry_run:
            cur.execute("""
                SELECT COUNT(*) FROM loan_requests
                WHERE request_status = 'open'
                  AND created_at < NOW() - (%s || ' days')::INTERVAL
            """, (str(days),))
            count = cur.fetchone()[0]
            return count, None

        cur.execute("""
            UPDATE loan_requests
            SET request_status = 'expired', updated_at = NOW()
            WHERE request_status = 'open'
              AND created_at < NOW() - (%s || ' days')::INTERVAL
        """, (str(days),))
        count = cur.rowcount
        conn.commit()
        if count:
            log_event("loan_requests_expired", target_user="system", source="system",
                      details={"count": count, "days_threshold": days})
        return count, None
    except Exception as e:
        conn.rollback()
        return 0, str(e)
    finally:
        cur.close()
        conn.close()


def search_loan_requests(
    q: str = None,
    status: str = None,
    amount_min=None,
    amount_max=None,
    limit: int = 50,
    offset: int = 0,
):
    """
    Search loan requests by username, request_id, post ID, or amount.
    Returns (results, total, error).
    """
    conn = _get_db()
    if not conn:
        return [], 0, "Database connection failed"
    try:
        _ensure_loan_requests_table(conn)
        cur = conn.cursor()
        conditions, params = [], []
        if q:
            conditions.append("""(
                lower(lr.borrower_username) LIKE lower(%s)
                OR lower(lr.reddit_username) LIKE lower(%s)
                OR lower(lr.request_id) LIKE lower(%s)
                OR lr.reddit_post_id = %s
            )""")
            like = f"%{q}%"
            params += [like, like, like, q]
        if status:
            conditions.append("lr.request_status = %s"); params.append(status)
        if amount_min is not None:
            conditions.append("lr.requested_amount >= %s"); params.append(amount_min)
        if amount_max is not None:
            conditions.append("lr.requested_amount <= %s"); params.append(amount_max)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        cur.execute(f"SELECT COUNT(*) FROM loan_requests lr {where}", params)
        total = cur.fetchone()[0]

        cur.execute(f"""
            SELECT lr.request_id, lr.borrower_username, lr.requested_amount,
                   lr.request_status, lr.thread_url, lr.created_at
            FROM loan_requests lr
            {where}
            ORDER BY lr.created_at DESC
            LIMIT %s OFFSET %s
        """, params + [limit, offset])
        cols = ["request_id","borrower_username","requested_amount","request_status",
                "thread_url","created_at"]
        rows = []
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            if d["created_at"]: d["created_at"] = str(d["created_at"])
            if d["requested_amount"]: d["requested_amount"] = float(d["requested_amount"])
            d["_type"] = "loan_request"
            rows.append(d)
        return rows, total, None
    except Exception as e:
        return [], 0, str(e)
    finally:
        cur.close()
        conn.close()
'''

path = os.path.join(os.path.dirname(__file__), "services.py")
with open(path, "a", encoding="utf-8") as f:
    f.write(APPEND)
print("Done — appended loan request services to services.py")
