"""
Move records saved under a misspelled Reddit name onto the right one.

    python scripts/rename_reddit_user.py embarrassed-throat42 embarassed-throat42          # preview
    python scripts/rename_reddit_user.py embarrassed-throat42 embarassed-throat42 --apply  # do it

Uses the database in .env (DB_HOST / DATABASE_URL), like the other scripts.

Renames the name in the record-keeping tables: loans (lender, borrower), the
old bot's users table (counts are merged when both names exist),
loan_requests and loan_offers. History (audit log, loan events) is left as it
happened. Everything changes in one transaction, and the rename is written to
the audit log.

Refuses when the old name has a dashboard account (user_roles): that account
has its own keys and settings, and should be linked instead (admin > lender >
"Link Reddit username").
"""

import argparse
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

NAME = re.compile(r"^[a-z0-9_-]{3,20}$")

#: (table, column) pairs holding a Reddit name as a record of who did what.
RECORD_COLUMNS = (
    ("loans", "lender"),
    ("loans", "borrower"),
    ("loan_requests", "borrower_username"),
    ("loan_requests", "reddit_username"),
    ("loan_offers", "lender"),
    ("loan_offers", "borrower"),
)


def _clean(name):
    name = (name or "").strip().lower()
    if name.startswith("u/"):
        name = name[2:]
    if not NAME.match(name):
        raise SystemExit(f"Not a Reddit username: {name!r}")
    return name


def _table_exists(cur, table):
    try:
        cur.execute(f"SELECT 1 FROM {table} LIMIT 1")
        cur.fetchall()
        return True
    except Exception:
        return False


def plan(cur, old):
    """{(table, column): rows} for every place the old name appears."""
    counts = {}
    for table, column in RECORD_COLUMNS:
        cur.execute(f"SELECT count(*) FROM {table} WHERE lower({column}) = %s", (old,))
        n = cur.fetchone()[0]
        if n:
            counts[(table, column)] = n
    return counts


def rename(conn, old, new, apply=False, actor="rename_reddit_user"):
    """Returns (counts, message). Changes nothing unless apply=True."""
    cur = conn.cursor()
    if old == new:
        return {}, "The names are the same."
    cur.execute("SELECT username FROM user_roles WHERE lower(username) = %s", (old,))
    if cur.fetchone():
        return None, (f"u/{old} has a dashboard account. Link it instead of renaming "
                      f"(admin > lender profile > Link Reddit username).")
    counts = plan(cur, old)
    has_users = _table_exists(cur, "users")
    users_old = users_new = None
    if has_users:
        cur.execute("SELECT loans_as_borrower, loans_as_lender FROM users WHERE lower(username) = %s", (old,))
        users_old = cur.fetchone()
        cur.execute("SELECT loans_as_borrower, loans_as_lender FROM users WHERE lower(username) = %s", (new,))
        users_new = cur.fetchone()
        if users_old:
            counts[("users", "username")] = 1
    if not counts:
        return {}, f"Nothing is recorded under u/{old}."
    if not apply:
        conn.rollback()
        return counts, "Preview only."

    for table, column in RECORD_COLUMNS:
        if (table, column) in counts:
            cur.execute(f"UPDATE {table} SET {column} = %s WHERE lower({column}) = %s", (new, old))
    if users_old:
        if users_new:
            cur.execute("""
                UPDATE users SET loans_as_borrower = COALESCE(loans_as_borrower, 0) + %s,
                                 loans_as_lender = COALESCE(loans_as_lender, 0) + %s
                WHERE lower(username) = %s
            """, (users_old[0] or 0, users_old[1] or 0, new))
            cur.execute("DELETE FROM users WHERE lower(username) = %s", (old,))
        else:
            cur.execute("UPDATE users SET username = %s WHERE lower(username) = %s", (new, old))
    conn.commit()

    import services
    services.log_audit(actor, "admin", "reddit_username_renamed", "user", new,
                       old_value={"reddit_username": old},
                       new_value={"reddit_username": new,
                                  "rows": {f"{t}.{c}": n for (t, c), n in counts.items()}})
    return counts, "Renamed."


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("old", help="the misspelled name records were saved under")
    parser.add_argument("new", help="the real Reddit name")
    parser.add_argument("--apply", action="store_true", help="actually change the records")
    args = parser.parse_args(argv)
    load_dotenv(ROOT / ".env", override=False)

    old, new = _clean(args.old), _clean(args.new)
    import utils
    conn = utils.get_db_connection()
    if conn is None:
        raise SystemExit("Could not connect to the database.")
    try:
        counts, message = rename(conn, old, new, apply=args.apply)
    finally:
        conn.close()
    if counts is None:
        raise SystemExit(message)
    for (table, column), n in sorted(counts.items()):
        print(f"  {table}.{column:<20} {n:>5} row(s)")
    print(message if args.apply or not counts else
          f"Preview only; nothing changed. Re-run with --apply to rename u/{old} to u/{new}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
