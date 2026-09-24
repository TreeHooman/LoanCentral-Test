"""
Local SQLite database for offline dashboard development.

Production uses PostgreSQL. This file only exists so the dashboard and service
tests can run safely without Reddit credentials or a local Postgres install.
"""

import os
import re
import sqlite3
from datetime import date, datetime
from decimal import Decimal


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(PROJECT_ROOT, "data", "loancentral_dev.sqlite3")

# Skip the schema/migration checks after the first successful run in this process.
# Schema shape doesn't change while the process is alive, so the 12+ PRAGMA calls
# per connection open are wasted after the first time.
_schema_applied: set = set()  # keyed by db_path


def _adapt_datetime(value):
    return value.isoformat(sep=" ")


def _convert_datetime(value):
    text = value.decode("utf-8")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime.strptime(text.split(".")[0], "%Y-%m-%d %H:%M:%S")


def _convert_date(value):
    text = value.decode("utf-8")
    if not text:
        return None
    return date.fromisoformat(text[:10])


sqlite3.register_adapter(datetime, _adapt_datetime)
sqlite3.register_adapter(date, lambda value: value.isoformat())
sqlite3.register_adapter(Decimal, float)
sqlite3.register_converter("TIMESTAMP", _convert_datetime)
sqlite3.register_converter("DATE", _convert_date)


# Timestamps are written by Python with datetime.now() (local), so every
# "now" SQLite computes has to be local too. CURRENT_TIMESTAMP and
# datetime('now') are UTC, and mixing the two silently skewed every date-window
# query by the machine's UTC offset — which is how the Reddit sync backoff came
# to expire instantly (see reddit_sync.due_actions).
_SQLITE_NOW = "datetime('now','localtime')"
_SQLITE_TODAY = "date('now','localtime')"


def _translate_sql(sql):
    """Rewrite the project's PostgreSQL into something SQLite can run.

    Production is Postgres; this exists so dev, tests and the demo exercise the
    same code. Everything here was added because a real query failed without
    it — dialect gaps meant roughly a third of the service layer could not run
    in dev at all, so those paths could be neither demoed nor tested.
    """
    sql = re.sub(r"\bSERIAL\s+PRIMARY\s+KEY\b", "INTEGER PRIMARY KEY AUTOINCREMENT", sql, flags=re.I)
    sql = re.sub(r"\bJSONB\b", "TEXT", sql, flags=re.I)

    # --- intervals ---------------------------------------------------------
    # Most specific first: each of these would otherwise be eaten by a later,
    # looser rule.

    # NOW() + (%s * INTERVAL '1 day')  — days come from a bound parameter
    sql = re.sub(
        r"\bNOW\(\)\s*([-+])\s*\(\s*%s\s*\*\s*INTERVAL\s*'1\s+day'\s*\)",
        lambda m: f"datetime('now','localtime','{m.group(1)}' || %s || ' days')",
        sql, flags=re.I)

    # NOW() - (%s || ' days')::INTERVAL
    sql = re.sub(
        r"\bNOW\(\)\s*([-+])\s*\(\s*%s\s*\|\|\s*'\s*(\w+)\s*'\s*\)\s*::\s*INTERVAL",
        lambda m: f"datetime('now','localtime','{m.group(1)}' || %s || ' {m.group(2)}')",
        sql, flags=re.I)

    # NOW() - %s::INTERVAL  — the whole interval ("30 days") is the parameter
    sql = re.sub(
        r"\bNOW\(\)\s*([-+])\s*%s\s*::\s*INTERVAL",
        lambda m: f"datetime('now','localtime','{m.group(1)}' || %s)",
        sql, flags=re.I)

    # CURRENT_DATE ± INTERVAL '7 days'
    sql = re.sub(
        r"\bCURRENT_DATE\s*([-+])\s*INTERVAL\s*'(\d+)\s+(\w+)'",
        lambda m: f"date('now','localtime','{m.group(1)}{m.group(2)} {m.group(3)}')",
        sql, flags=re.I)

    # NOW() ± INTERVAL '30 days'
    sql = re.sub(
        r"\bNOW\(\)\s*([-+])\s*INTERVAL\s*'(\d+)\s+(\w+)'",
        lambda m: f"datetime('now','localtime','{m.group(1)}{m.group(2)} {m.group(3)}')",
        sql, flags=re.I)

    # column ± INTERVAL '10 days'  (e.g. r1.created_at - INTERVAL '10 days')
    sql = re.sub(
        r"([\w.]+)\s*([-+])\s*INTERVAL\s*'(\d+)\s+(\w+)'",
        lambda m: f"datetime({m.group(1)},'{m.group(2)}{m.group(3)} {m.group(4)}')",
        sql, flags=re.I)

    # EXTRACT(EPOCH FROM (a - b)) — seconds between two timestamps.
    sql = re.sub(
        r"\bEXTRACT\(\s*EPOCH\s+FROM\s*\(\s*([\w.]+)\s*-\s*([\w.]+)\s*\)\s*\)",
        r"((julianday(\1) - julianday(\2)) * 86400.0)",
        sql, flags=re.I)

    # --- date_trunc --------------------------------------------------------
    # 'week' matches Postgres, which truncates to Monday: step forward to the
    # coming Sunday, then back six days.
    sql = re.sub(r"\bDATE_TRUNC\(\s*'month'\s*,\s*NOW\(\)\s*\)",
                 f"strftime('%Y-%m-01',{_SQLITE_NOW})", sql, flags=re.I)
    sql = re.sub(r"\bDATE_TRUNC\(\s*'month'\s*,\s*([^)]+)\)",
                 r"strftime('%Y-%m-01',\1)", sql, flags=re.I)
    sql = re.sub(r"\bDATE_TRUNC\(\s*'day'\s*,\s*([^)]+)\)",
                 r"date(\1)", sql, flags=re.I)
    sql = re.sub(r"\bDATE_TRUNC\(\s*'week'\s*,\s*([^)]+)\)",
                 r"date(\1,'weekday 0','-6 days')", sql, flags=re.I)

    # --- remaining casts and functions ------------------------------------
    sql = re.sub(r"\bid::text\b", "CAST(id AS TEXT)", sql, flags=re.I)
    sql = re.sub(r"::date\b", "", sql, flags=re.I)
    # A column DEFAULT must be a literal or a *parenthesised* expression in
    # SQLite, so this cannot share the general NOW() rule below.
    sql = re.sub(r"\bDEFAULT\s+NOW\(\)", f"DEFAULT ({_SQLITE_NOW})", sql, flags=re.I)
    sql = re.sub(r"\bNOW\(\)", _SQLITE_NOW, sql, flags=re.I)
    sql = re.sub(r"\bCURRENT_DATE\b", _SQLITE_TODAY, sql, flags=re.I)
    sql = re.sub(r"\bILIKE\b", "LIKE", sql, flags=re.I)
    return sql.replace("%s", "?")


class SQLiteCompatCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, sql, params=None):
        if params is None:
            params = ()
        self._cursor.execute(_translate_sql(sql), params)
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def close(self):
        self._cursor.close()

    @property
    def rowcount(self):
        return self._cursor.rowcount


class SQLiteCompatConnection:
    is_sqlite = True

    def __init__(self, connection):
        self._connection = connection

    def cursor(self):
        return SQLiteCompatCursor(self._connection.cursor())

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()


def _ensure_column(conn, table, column, definition):
    existing = {
        row[1]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


# loan_requests was renamed from the old bot column names to the dashboard names.
# Prod was migrated by migrations/migrate_loan_requests.py; this is the SQLite
# equivalent so an existing dev/test DB created before the rename keeps working.
_LOAN_REQUEST_RENAMES = [
    ("borrower", "borrower_username"),
    ("amount", "requested_amount"),
    ("repay_amount", "requested_repayment_amount"),
    ("repay_date", "requested_due_date"),
    ("status", "request_status"),
    ("thread_link", "thread_url"),
]


def _table_exists(conn, table):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _migrate_legacy_loan_requests(conn):
    """Rename pre-rename loan_requests columns in place, before schema.sql runs.

    schema.sql indexes borrower_username, so this has to happen first or the
    whole script aborts on an older DB file.
    """
    if not _table_exists(conn, "loan_requests"):
        return
    columns = {row[1] for row in conn.execute("PRAGMA table_info(loan_requests)").fetchall()}
    for old_name, new_name in _LOAN_REQUEST_RENAMES:
        if old_name in columns and new_name not in columns:
            conn.execute(f"ALTER TABLE loan_requests RENAME COLUMN {old_name} TO {new_name}")
            columns.discard(old_name)
            columns.add(new_name)
    conn.commit()


def _ensure_schema(conn):
    _migrate_legacy_loan_requests(conn)

    schema_path = os.path.join(PROJECT_ROOT, "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = _translate_sql(f.read())
    conn.executescript(schema)

    _ensure_column(conn, "loans", "loan_id", "TEXT UNIQUE")
    _ensure_column(conn, "loans", "repay_amount", "NUMERIC")
    _ensure_column(conn, "loans", "repay_date", "DATE")
    _ensure_column(conn, "loans", "payment_method", "TEXT")
    _ensure_column(conn, "loans", "borrower_acknowledged_at", "TIMESTAMP")
    _ensure_column(conn, "loans", "borrower_acknowledged_note", "TEXT")
    _ensure_column(conn, "loans", "notes", "TEXT")
    _ensure_column(conn, "loans", "interest_amount", "NUMERIC")
    _ensure_column(conn, "loans", "interest_rate", "NUMERIC")
    _ensure_column(conn, "loans", "payment_timing", "TEXT")
    _ensure_column(conn, "loan_requests", "lender_note", "TEXT")
    _ensure_column(conn, "loan_requests", "expires_at", "TIMESTAMP")
    # Columns the dashboard schema added after the rename
    _ensure_column(conn, "loan_requests", "reddit_username", "VARCHAR(100)")
    _ensure_column(conn, "loan_requests", "reddit_comment_id", "VARCHAR(30)")
    _ensure_column(conn, "loan_requests", "updated_at", "TIMESTAMP")
    _ensure_column(conn, "loan_requests", "funded_loan_id", "INTEGER")
    _ensure_column(conn, "loan_requests", "notes", "TEXT")
    # Verified lender columns on user_roles
    _ensure_column(conn, "user_roles", "verified_lender", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "user_roles", "verified_lender_at", "TIMESTAMP")
    _ensure_column(conn, "user_roles", "verified_lender_by", "TEXT")
    _ensure_column(conn, "user_roles", "verification_note", "TEXT")
    _ensure_column(conn, "user_roles", "contact_email", "TEXT")
    _ensure_column(conn, "user_roles", "contact_phone", "TEXT")
    _ensure_column(conn, "user_roles", "perm_version", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "user_roles", "reddit_username", "TEXT")
    _ensure_column(conn, "user_roles", "reddit_username_linked_at", "TIMESTAMP")
    _ensure_column(conn, "user_roles", "reddit_username_linked_by", "TEXT")
    _ensure_column(conn, "user_roles", "google_sub", "TEXT")
    _ensure_column(conn, "user_roles", "google_email", "TEXT")
    _ensure_column(conn, "user_roles", "google_linked_at", "TIMESTAMP")
    _ensure_column(conn, "user_roles", "legacy_lender", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "user_roles", "legacy_granted_by", "TEXT")
    _ensure_column(conn, "user_roles", "legacy_granted_at", "TIMESTAMP")
    # Retry bookkeeping for the Reddit sync worker. Postgres gets these from
    # scripts/migrations/013_integrity_constraints.sql.
    _ensure_column(conn, "reddit_actions", "attempts", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "reddit_actions", "next_attempt_at", "TIMESTAMP")
    _ensure_column(conn, "reddit_actions", "last_error", "TEXT")
    conn.commit()

    _ensure_unique_indexes(conn)


# Uniqueness guarantees that back the Python-side invariants. Postgres gets the
# same set from scripts/migrations/013_integrity_constraints.sql; this is the
# SQLite half so dev and test behave like production.
#
# Each runs on its own: an existing dev database may already hold duplicates,
# and one unbuildable index must not stop the others. Run
# `python scripts/check_db_integrity.py` to see what is blocking one.
_UNIQUE_INDEXES = [
    ("uq_lr_reddit_post_id",
     "CREATE UNIQUE INDEX IF NOT EXISTS uq_lr_reddit_post_id "
     "ON loan_requests (reddit_post_id) WHERE reddit_post_id IS NOT NULL"),
    ("uq_lr_funded_loan_id",
     "CREATE UNIQUE INDEX IF NOT EXISTS uq_lr_funded_loan_id "
     "ON loan_requests (funded_loan_id) WHERE funded_loan_id IS NOT NULL"),
    ("uq_loans_loan_id",
     "CREATE UNIQUE INDEX IF NOT EXISTS uq_loans_loan_id "
     "ON loans (loan_id) WHERE loan_id IS NOT NULL"),
    ("uq_user_roles_google_sub",
     "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_roles_google_sub "
     "ON user_roles (google_sub) WHERE google_sub IS NOT NULL"),
]


def _ensure_unique_indexes(conn):
    for name, statement in _UNIQUE_INDEXES:
        try:
            conn.execute(statement)
            conn.commit()
        except sqlite3.Error as exc:
            conn.rollback()
            print(f"[SCHEMA] unique index {name} not applied: {exc}")


def get_sqlite_connection(path=None):
    db_path = path or os.getenv("SQLITE_DB_PATH", DEFAULT_DB_PATH)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    already_set_up = db_path in _schema_applied
    conn = sqlite3.connect(
        db_path,
        detect_types=sqlite3.PARSE_DECLTYPES,
        timeout=30,
    )
    conn.execute("PRAGMA foreign_keys = ON")
    conn.create_function("GREATEST", -1, lambda *values: max(v for v in values if v is not None))
    if not already_set_up:
        _ensure_schema(conn)
        _schema_applied.add(db_path)
    return SQLiteCompatConnection(conn)
