"""
Run LoanCentral SQL migrations (PostgreSQL).

Before this had tracking, every run re-executed all 11 files and nothing
recorded what the database had actually seen. Now each file is applied once, in
its own transaction, and recorded in `schema_migrations` with a checksum so an
edited migration is caught instead of silently skipped.

Usage:
    python scripts/run_migrations.py            # apply pending migrations
    python scripts/run_migrations.py --status   # show applied / pending, apply nothing

Safe default: refuses to run when LOANCENTRAL_ENV=prod unless
ALLOW_PROD_MIGRATIONS=yes is set. Back up first — see docs/BACKUP_RESTORE.md.
"""

import hashlib
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils import get_db_connection  # noqa: E402
from sqlscript import split_sql  # noqa: E402,F401  (re-exported for tests)

MIGRATIONS_DIR = ROOT / "scripts" / "migrations"
TRACKING_MIGRATION = "012_schema_migrations.sql"


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def ensure_tracking_table(conn):
    """Create schema_migrations if absent, using the tracking migration itself."""
    cur = conn.cursor()
    try:
        for statement in split_sql((MIGRATIONS_DIR / TRACKING_MIGRATION).read_text(encoding="utf-8")):
            cur.execute(statement)
        conn.commit()
    finally:
        cur.close()


def applied_migrations(conn):
    cur = conn.cursor()
    try:
        cur.execute("SELECT filename, checksum FROM schema_migrations")
        return {row[0]: row[1] for row in cur.fetchall() or []}
    finally:
        cur.close()


def record(conn, path):
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO schema_migrations (filename, checksum, applied_by) VALUES (%s, %s, %s)",
            (path.name, checksum(path), os.getenv("USERNAME") or os.getenv("USER") or "unknown"),
        )
    finally:
        cur.close()


def apply_migration(conn, path):
    """Apply one migration and record it in the same transaction."""
    cur = conn.cursor()
    try:
        for statement in split_sql(path.read_text(encoding="utf-8")):
            cur.execute(statement)
    finally:
        cur.close()
    record(conn, path)
    conn.commit()


def main():
    load_dotenv(ROOT / ".env")
    status_only = "--status" in sys.argv

    env = os.getenv("LOANCENTRAL_ENV", "prod").lower()
    if env == "prod" and not status_only and os.getenv("ALLOW_PROD_MIGRATIONS") != "yes":
        print("Refusing to run migrations with LOANCENTRAL_ENV=prod.")
        print("For production, backup first, then run with ALLOW_PROD_MIGRATIONS=yes.")
        return 2

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        print("No migration files found.")
        return 0

    conn = get_db_connection()
    if not conn:
        print("Database connection failed.")
        return 1

    if getattr(conn, "is_sqlite", False):
        conn.close()
        print("These migrations are PostgreSQL-only.")
        print("SQLite dev/test databases are built by local_db._ensure_schema() instead.")
        return 2

    try:
        if status_only:
            # Read-only: never create the tracking table just to look. A
            # database that has not got it yet simply shows everything pending.
            try:
                done = applied_migrations(conn)
            except Exception:
                conn.rollback()
                done = {}
        else:
            ensure_tracking_table(conn)
            done = applied_migrations(conn)

        if status_only:
            for path in files:
                if path.name not in done:
                    print(f"  pending  {path.name}")
                elif done[path.name] != checksum(path):
                    print(f"  CHANGED  {path.name}  (applied checksum {done[path.name]}, file is {checksum(path)})")
                else:
                    print(f"  applied  {path.name}")
            return 0

        changed = [p.name for p in files
                   if p.name in done and done[p.name] != checksum(p)]
        if changed:
            print("Refusing to run: these migrations changed after being applied:")
            for name in changed:
                print(f"  {name}")
            print("Migrations are immutable once applied — add a new file instead.")
            return 1

        pending = [p for p in files if p.name not in done]
        if not pending:
            print("Database is up to date.")
            return 0

        for path in pending:
            print(f"Applying {path.name}...")
            try:
                apply_migration(conn, path)
            except Exception as exc:
                conn.rollback()
                print(f"Migration failed: {path.name}: {exc}")
                print("No partial changes were kept — this file ran in its own transaction.")
                return 1

        print(f"Applied {len(pending)} migration(s).")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
