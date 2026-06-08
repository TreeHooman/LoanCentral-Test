"""
Run LoanCentral SQL migrations.

Safe default: refuses to run when LOANCENTRAL_ENV=prod unless
ALLOW_PROD_MIGRATIONS=yes is set.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils import get_db_connection  # noqa: E402


def split_sql(sql_text):
    statements = []
    current = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        current.append(line)
        if stripped.endswith(";"):
            statements.append("\n".join(current))
            current = []
    if current:
        statements.append("\n".join(current))
    return statements


def main():
    load_dotenv(ROOT / ".env")
    env = os.getenv("LOANCENTRAL_ENV", "prod").lower()
    if env == "prod" and os.getenv("ALLOW_PROD_MIGRATIONS") != "yes":
        print("Refusing to run migrations with LOANCENTRAL_ENV=prod.")
        print("For production, backup first, then run with ALLOW_PROD_MIGRATIONS=yes.")
        return 2

    migrations_dir = ROOT / "scripts" / "migrations"
    files = sorted(migrations_dir.glob("*.sql"))
    if not files:
        print("No migration files found.")
        return 0

    conn = get_db_connection()
    if not conn:
        print("Database connection failed.")
        return 1

    try:
        cur = conn.cursor()
        for path in files:
            print(f"Running {path.name}...")
            for statement in split_sql(path.read_text(encoding="utf-8")):
                cur.execute(statement)
        conn.commit()
        print("Migrations complete.")
        return 0
    except Exception as exc:
        conn.rollback()
        print(f"Migration failed: {exc}")
        return 1
    finally:
        try:
            cur.close()
        finally:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
