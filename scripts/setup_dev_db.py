"""
Dev database setup — run once (or any time) to reset your local dev DB.

What it does:
  1. Drops and recreates the loancentral_dev database
  2. Loads the real backup via psql (handles COPY blocks correctly)
  3. Runs all migrations (adds missing columns, user_roles, etc.)
  4. Seeds roles so logistix1 and other real lenders show the lender dashboard

Run:
  python scripts/setup_dev_db.py
"""

import os
import sys
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env.test"), override=True)

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = os.getenv("DB_PORT", "5432")
DB_USER     = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DEV_DB      = "loancentral_dev"

# Find psql on this machine
PSQL_CANDIDATES = [
    r"C:\Program Files\PostgreSQL\18\bin\psql.exe",
    r"C:\Program Files\PostgreSQL\17\bin\psql.exe",
    r"C:\Program Files\PostgreSQL\16\bin\psql.exe",
    "psql",
]

BACKUP_SQL = os.path.join(ROOT, "data", "imports", "BACKUP V2.restored.sql")
MIGRATIONS = [
    os.path.join(ROOT, "scripts", "migrations", "001_dashboard_columns.sql"),
    os.path.join(ROOT, "scripts", "migrations", "002_verification_applications.sql"),
    os.path.join(ROOT, "scripts", "migrations", "003_reddit_actions.sql"),
    os.path.join(ROOT, "scripts", "migrations", "004_interest_tracking.sql"),
    os.path.join(ROOT, "scripts", "migrations", "005_lender_keys.sql"),
    os.path.join(ROOT, "scripts", "migrations", "006_borrower_auth.sql"),
    os.path.join(ROOT, "scripts", "migrations", "007_magic_links.sql"),
]


def find_psql():
    for candidate in PSQL_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
        try:
            subprocess.run([candidate, "--version"], capture_output=True, timeout=3)
            return candidate
        except Exception:
            pass
    return None


def run_psql(psql, dbname, sql_file):
    env = os.environ.copy()
    env["PGPASSWORD"] = DB_PASSWORD
    result = subprocess.run(
        [psql, "-h", DB_HOST, "-p", str(DB_PORT), "-U", DB_USER, "-d", dbname, "-f", sql_file],
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Print errors but don't abort — some warnings are harmless
        for line in result.stderr.splitlines():
            if "ERROR" in line:
                print(f"  [error] {line}")
    return result.returncode


def connect(dbname="postgres"):
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT,
        dbname=dbname, user=DB_USER, password=DB_PASSWORD
    )


def main():
    psql = find_psql()
    if not psql:
        print("ERROR: psql not found. Make sure PostgreSQL is installed.")
        sys.exit(1)
    print(f"Using psql: {psql}")
    print(f"Connecting to Postgres at {DB_HOST}:{DB_PORT} as {DB_USER}...")

    # --- Step 1: drop and recreate dev DB ---
    conn = connect("postgres")
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DEV_DB,))
    if cur.fetchone():
        print(f"Dropping existing '{DEV_DB}'...")
        cur.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(DEV_DB)))
    print(f"Creating '{DEV_DB}'...")
    cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DEV_DB)))
    cur.close()
    conn.close()

    # --- Step 2: load backup via psql ---
    print(f"\nLoading backup...")
    rc = run_psql(psql, DEV_DB, BACKUP_SQL)
    print(f"  done (exit code {rc})")

    # --- Step 3: run migrations ---
    for path in MIGRATIONS:
        print(f"\nRunning migration: {os.path.basename(path)}")
        rc = run_psql(psql, DEV_DB, path)
        print(f"  done (exit code {rc})")

    # --- Step 4: seed roles ---
    print("\nSeeding roles...")
    conn = connect(DEV_DB)
    cur = conn.cursor()
    roles = [
        ("logistix1",            "lender"),
        ("testlender",           "lender"),
        ("testmod",              "mod"),
        ("testadmin",            "admin"),
        ("embarrassed-throat42", "lender"),
        ("dmath706",             "lender"),
        ("galwall",              "lender"),
        ("left-associate3911",   "lender"),
        ("quiet_string97",       "lender"),
        ("entrepreneurprior334", "lender"),
        ("exposing_scammerz",    "lender"),
    ]
    for username, role in roles:
        cur.execute("""
            INSERT INTO user_roles (username, role)
            VALUES (%s, %s)
            ON CONFLICT (username) DO UPDATE SET role = %s
        """, (username, role, role))
    conn.commit()
    cur.close()
    conn.close()
    print(f"  seeded {len(roles)} roles")

    print(f"\nAll done! Dev DB '{DEV_DB}' is ready.")
    print("Start the dashboard:  python run_dev.py")


if __name__ == "__main__":
    main()
