"""
Launch day: load the main bot database's dump into the shared database (Neon).

The old bot's database lives on the bot computer. 2.0's bot and dashboard both
use the database in .env (DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD), which
is Neon. This moves the one into the other and upgrades it, in one run:

  1. read the dump and count its rows per table
  2. back up whatever the target holds now (backup_prod_db.py)
  3. empty the target (drop and recreate the public schema)
  4. restore the dump
  5. check every table's row count matches the dump
  6. apply the migrations, then check the counts again (migrations only add)
  7. run the read-only integrity check

Preview (changes nothing; shows the dump's contents and the target):

    python scripts/load_main_db.py backups\\main_launch.dump

Apply. --target-host must repeat DB_HOST exactly, so a wrong .env cannot
empty the wrong database:

    python scripts/load_main_db.py backups\\main_launch.dump --apply --target-host ep-....neon.tech

Accepts pg_dump custom format (.dump, what pgAdmin writes) and plain SQL
(.sql or .sql.gz). Roles are the next, separate step: scripts/bootstrap_roles.py.
"""

import argparse
import gzip
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PG_BIN_CANDIDATES = [rf"C:\Program Files\PostgreSQL\{v}\bin" for v in (18, 17, 16)]


def find_tool(name):
    found = shutil.which(name)
    if found:
        return found
    for folder in PG_BIN_CANDIDATES:
        exe = Path(folder) / f"{name}.exe"
        if exe.exists():
            return str(exe)
    raise SystemExit(f"{name} not found. Install the PostgreSQL client tools (version 17 or newer).")


def target():
    cfg = {k: (os.getenv(k) or "").strip() for k in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")}
    cfg["DB_PORT"] = cfg["DB_PORT"] or "5432"
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        raise SystemExit(f"Set {', '.join(missing)} in .env first.")
    return cfg


def pg_env(cfg):
    env = os.environ.copy()
    env.update(PGHOST=cfg["DB_HOST"], PGPORT=cfg["DB_PORT"], PGDATABASE=cfg["DB_NAME"],
               PGUSER=cfg["DB_USER"], PGPASSWORD=cfg["DB_PASSWORD"])
    local = cfg["DB_HOST"] in ("localhost", "127.0.0.1", "::1")
    env.setdefault("PGSSLMODE", "prefer" if local else "require")
    return env


def run(cmd, env, what):
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise SystemExit(f"{what} failed:\n{result.stderr.strip() or result.stdout.strip()}")
    return result.stdout


def dump_to_plain_sql(dump_path, workdir):
    """Return a plain-SQL copy of the dump, whatever format it arrived in."""
    with open(dump_path, "rb") as f:
        head = f.read(5)
    out = Path(workdir) / "restore.sql"
    if head == b"PGDMP":
        run([find_tool("pg_restore"), "--no-owner", "--no-acl", "-f", str(out), str(dump_path)],
            os.environ.copy(), "Reading the custom-format dump")
    elif head[:2] == b"\x1f\x8b":
        with gzip.open(dump_path, "rb") as src, open(out, "wb") as dst:
            shutil.copyfileobj(src, dst)
    else:
        shutil.copyfile(dump_path, out)
    return out


def rows_in_dump(sql_path):
    """Row counts per table from the dump's COPY blocks (pg_dump's default)."""
    counts, table = {}, None
    copy_re = re.compile(r"^COPY (?:public\.)?\"?([A-Za-z0-9_]+)\"? ")
    with open(sql_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if table is None:
                m = copy_re.match(line)
                if m:
                    table = m.group(1)
                    counts[table] = 0
            elif line.rstrip("\r\n") == "\\.":
                table = None
            else:
                counts[table] += 1
    return counts


def rows_in_target(cfg, tables):
    psql = find_tool("psql")
    counts = {}
    for t in tables:
        out = run([psql, "-At", "-c", f'SELECT COUNT(*) FROM public."{t}"'], pg_env(cfg), f"Counting {t}")
        counts[t] = int(out.strip())
    return counts


def compare(expected, actual, when):
    bad = {t: (n, actual.get(t)) for t, n in expected.items() if actual.get(t) != n}
    if bad:
        for t, (want, got) in bad.items():
            print(f"  MISMATCH {t}: dump has {want}, database has {got}")
        raise SystemExit(f"Row counts do not match {when}. Stop and investigate; the "
                         "pre-load backup is in backups/.")
    print(f"  OK  every table matches the dump {when}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dump", help="the main database's pg_dump file")
    parser.add_argument("--apply", action="store_true", help="actually replace the target database")
    parser.add_argument("--target-host", default="", help="must equal DB_HOST; required with --apply")
    parser.add_argument("--skip-backup", action="store_true",
                        help="don't back up the target first (only for a throwaway target)")
    args = parser.parse_args()
    # Child scripts print em dashes; a cp1252 Windows console would crash on them.
    sys.stdout.reconfigure(errors="replace")

    load_dotenv(ROOT / ".env", override=False)
    cfg = target()
    dump_path = Path(args.dump)
    if not dump_path.is_file():
        raise SystemExit(f"No such file: {dump_path}")

    with tempfile.TemporaryDirectory() as workdir:
        sql = dump_to_plain_sql(dump_path, workdir)
        expected = rows_in_dump(sql)
        if not expected:
            raise SystemExit("The dump contains no table data (no COPY blocks). Is it the right file?")

        print(f"Dump:   {dump_path.name}")
        for t, n in sorted(expected.items()):
            print(f"          {t:<28} {n:>7} rows")
        print(f"Target: {cfg['DB_USER']}@{cfg['DB_HOST']}:{cfg['DB_PORT']}/{cfg['DB_NAME']}")

        if not args.apply:
            print("\nPreview only; nothing changed. Re-run with "
                  f"--apply --target-host {cfg['DB_HOST']} to replace the target.")
            return 0
        if args.target_host.strip() != cfg["DB_HOST"]:
            raise SystemExit(f"Refusing: --target-host must be exactly {cfg['DB_HOST']!r} (from .env).")

        print("\n[1/6] Backing up the target's current contents")
        if args.skip_backup:
            print("  skipped (--skip-backup)")
        else:
            import backup_prod_db
            backup_prod_db.DB_HOST, backup_prod_db.DB_PORT = cfg["DB_HOST"], cfg["DB_PORT"]
            backup_prod_db.DB_NAME, backup_prod_db.DB_USER = cfg["DB_NAME"], cfg["DB_USER"]
            backup_prod_db.DB_PASS = cfg["DB_PASSWORD"]
            backup_prod_db.run_backup()

        psql = find_tool("psql")
        print("[2/6] Emptying the target")
        run([psql, "-v", "ON_ERROR_STOP=1", "-q", "-c",
             "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;"], pg_env(cfg), "Emptying the target")

        print("[3/6] Restoring the dump")
        run([psql, "-v", "ON_ERROR_STOP=1", "--single-transaction", "-q", "-f", str(sql)],
            pg_env(cfg), "Restoring the dump")

        print("[4/6] Checking row counts")
        compare(expected, rows_in_target(cfg, expected), "after the restore")

        print("[5/6] Applying migrations")
        env = pg_env(cfg)
        env["ALLOW_PROD_MIGRATIONS"] = "yes"
        env["PYTHONIOENCODING"] = "utf-8"
        print(run([sys.executable, str(ROOT / "scripts" / "run_migrations.py")], env, "Migrations").rstrip())
        compare(expected, rows_in_target(cfg, expected), "after the migrations")

        print("[6/6] Integrity check (read-only)")
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_db_integrity.py")],
                                env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        print(result.stdout.rstrip())

    print("\nDone. Next: scripts/bootstrap_roles.py (runbook step 5).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
