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


def _translate_sql(sql):
    sql = re.sub(r"\bSERIAL\s+PRIMARY\s+KEY\b", "INTEGER PRIMARY KEY AUTOINCREMENT", sql, flags=re.I)
    sql = re.sub(r"\bJSONB\b", "TEXT", sql, flags=re.I)
    sql = re.sub(r"\bNOW\(\)", "CURRENT_TIMESTAMP", sql, flags=re.I)
    sql = re.sub(r"\bid::text\b", "CAST(id AS TEXT)", sql, flags=re.I)
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


def _ensure_schema(conn):
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
    _ensure_column(conn, "loan_requests", "lender_note", "TEXT")
    _ensure_column(conn, "loan_requests", "expires_at", "TIMESTAMP")
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
    conn.commit()


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
