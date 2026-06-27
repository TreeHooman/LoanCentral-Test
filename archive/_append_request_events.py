"""Append request_events services and duplicate-detection helper to services.py."""
import os

APPEND = '''

# =============================================================================
# Request Events (Task 2 — Request Timeline)
# =============================================================================

_REQUEST_EVENT_TYPES = (
    "created",
    "status_changed",
    "linked_to_loan",
    "note_added",
    "expired",
    "detected_duplicate",
    "edited",
)


def _ensure_request_events_table(conn):
    """Lazy-create request_events table."""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS request_events (
            id          SERIAL       PRIMARY KEY,
            request_id  VARCHAR(20)  NOT NULL,
            event_type  VARCHAR(50)  NOT NULL,
            actor       VARCHAR(100),
            note        TEXT,
            created_at  TIMESTAMP    NOT NULL DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_request_events_request_id
            ON request_events (request_id)
    """)
    conn.commit()
    cur.close()


def log_request_event(request_id: str, event_type: str,
                      actor: str = None, note: str = None):
    """
    Append an event to the request timeline.
    Returns (event_id, error).
    """
    conn = _get_db()
    if not conn:
        return None, "Database connection failed"
    try:
        _ensure_request_events_table(conn)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO request_events (request_id, event_type, actor, note)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (request_id, event_type, actor, note))
        eid = cur.fetchone()[0]
        conn.commit()
        return eid, None
    except Exception as e:
        conn.rollback()
        return None, str(e)
    finally:
        cur.close()
        conn.close()


def get_request_events(request_id: str):
    """
    Return all timeline events for a loan request, oldest first.
    Returns (events_list, error).
    """
    conn = _get_db()
    if not conn:
        return [], "Database connection failed"
    try:
        _ensure_request_events_table(conn)
        cur = conn.cursor()
        cur.execute("""
            SELECT id, event_type, actor, note, created_at
            FROM request_events
            WHERE request_id = %s
            ORDER BY created_at ASC, id ASC
        """, (request_id,))
        events = []
        for row in cur.fetchall():
            events.append({
                "id":         row[0],
                "event_type": row[1],
                "actor":      row[2],
                "note":       row[3],
                "created_at": str(row[4]),
            })
        return events, None
    except Exception as e:
        return [], str(e)
    finally:
        cur.close()
        conn.close()


# =============================================================================
# Duplicate Request Detection (Task 7)
# =============================================================================

def find_duplicate_loan_requests(
    borrower_username: str,
    days: int = 10,
    exclude_request_id: str = None,
):
    """
    Find open loan requests from the same borrower within `days` days.
    Returns (duplicates_list, error).
    Each item has request_id, created_at, request_status.
    Does NOT auto-remove anything — surface only.
    """
    if not borrower_username:
        return [], "borrower_username required"
    conn = _get_db()
    if not conn:
        return [], "Database connection failed"
    try:
        _ensure_loan_requests_table(conn)
        cur = conn.cursor()
        params = [borrower_username.lower(), days]
        exclude_clause = ""
        if exclude_request_id:
            exclude_clause = "AND request_id != %s"
            params.append(exclude_request_id)
        cur.execute(f"""
            SELECT request_id, request_status, created_at, requested_amount
            FROM loan_requests
            WHERE lower(borrower_username) = lower(%s)
              AND request_status = 'open'
              AND created_at >= NOW() - (%s || ' days')::INTERVAL
              {exclude_clause}
            ORDER BY created_at DESC
        """, params)
        rows = []
        for r in cur.fetchall():
            rows.append({
                "request_id":       r[0],
                "request_status":   r[1],
                "created_at":       str(r[2]),
                "requested_amount": float(r[3]) if r[3] else None,
            })
        return rows, None
    except Exception as e:
        return [], str(e)
    finally:
        cur.close()
        conn.close()
'''

services_path = os.path.join(os.path.dirname(__file__), "services.py")
with open(services_path, "a", encoding="utf-8") as f:
    f.write(APPEND)
print("Done — appended request_events + duplicate detection services.")
