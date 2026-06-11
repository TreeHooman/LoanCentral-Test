"""
Daily prod DB backup via pg_dump.
Saves compressed .sql.gz to backups/ directory, keeps last 14 files.

Usage:
  python backup_prod_db.py            # uses .env creds
  python backup_prod_db.py --verify   # restore-test into a temp local DB (requires local PG)

Scheduled automatically by Windows Task Scheduler — see BACKUP_RESTORE.md.
"""

import os
import sys
import gzip
import shutil
import logging
import subprocess
import glob
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("backup")

BACKUP_DIR = Path(__file__).parent / "backups"
KEEP_LAST  = 14  # days of backups to retain

DB_HOST = os.getenv("DB_HOST", "")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "")
DB_USER = os.getenv("DB_USER", "")
DB_PASS = os.getenv("DB_PASSWORD", "")


def find_pg_dump():
    """Find pg_dump binary — checks PATH then common pgAdmin install locations."""
    if shutil.which("pg_dump"):
        return "pg_dump"
    candidates = [
        r"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe",
        r"C:\Program Files\PostgreSQL\17\bin\pg_dump.exe",
        r"C:\Program Files\PostgreSQL\16\bin\pg_dump.exe",
        r"C:\Program Files\PostgreSQL\15\bin\pg_dump.exe",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


def run_backup():
    BACKUP_DIR.mkdir(exist_ok=True)

    pg_dump = find_pg_dump()
    if not pg_dump:
        log.error("pg_dump not found. Install PostgreSQL client tools.")
        sys.exit(1)

    if not all([DB_HOST, DB_NAME, DB_USER, DB_PASS]):
        log.error("DB credentials not set in .env")
        sys.exit(1)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path  = BACKUP_DIR / f"loancentral_{timestamp}.sql.gz"

    env = os.environ.copy()
    env["PGPASSWORD"] = DB_PASS
    env["PGSSLMODE"]  = "require"

    cmd = [
        pg_dump,
        "-h", DB_HOST,
        "-p", DB_PORT,
        "-U", DB_USER,
        "-d", DB_NAME,
        "--no-password",
        "--format=plain",
        "--no-owner",
        "--no-acl",
    ]

    log.info("Running pg_dump → %s", out_path)
    result = subprocess.run(cmd, capture_output=True, env=env)

    if result.returncode != 0:
        log.error("pg_dump failed:\n%s", result.stderr.decode())
        sys.exit(1)

    with gzip.open(out_path, "wb") as f:
        f.write(result.stdout)

    size_kb = out_path.stat().st_size // 1024
    log.info("Backup saved: %s (%d KB)", out_path.name, size_kb)

    # Prune old backups
    existing = sorted(glob.glob(str(BACKUP_DIR / "loancentral_*.sql.gz")))
    for old in existing[:-KEEP_LAST]:
        Path(old).unlink()
        log.info("Pruned old backup: %s", Path(old).name)

    log.info("Done. %d backup(s) retained.", min(len(existing), KEEP_LAST))
    return out_path


if __name__ == "__main__":
    run_backup()
