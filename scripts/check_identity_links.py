"""
Read-only report on Reddit-handle vs dashboard-username identity problems.

Finds the data damage left by two historical bugs:
  * shadow rows - a user_roles row keyed on someone's Reddit handle, created by
    bot activity, shadowing that person's real (often verified) account;
  * split records - loans and stats written under a Reddit handle for a lender
    whose dashboard account uses a different name.

This script only SELECTs. Where a repair is possible it prints the SQL for you
to review and run yourself; it never writes to the database.

    python scripts/check_identity_links.py
"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from utils import get_db_connection  # noqa: E402


def q(cur, sql, args=()):
    cur.execute(sql, args)
    return cur.fetchall()


def section(title):
    print()
    print(title)
    print("-" * len(title))


def main():
    conn = get_db_connection()
    if not conn:
        sys.exit("Could not connect to the database.")
    cur = conn.cursor()
    findings = 0
    suggested = []

    section("1. Shadow user_roles rows (Reddit handle shadowing a real account)")
    rows = q(cur, """
        SELECT shadow.username, owner.username, owner.verified_lender, owner.role
        FROM user_roles shadow
        JOIN user_roles owner
          ON lower(owner.reddit_username) = lower(shadow.username)
         AND lower(owner.username) <> lower(shadow.username)
        ORDER BY shadow.username
    """)
    if not rows:
        print("  none")
    for shadow, owner, verified, role in rows:
        findings += 1
        print(f"  '{shadow}' shadows '{owner}' (owner role={role}, verified={bool(verified)})")
        suggested.append(
            f"-- move any activity off the shadow row, then:\n"
            f"DELETE FROM user_roles WHERE lower(username) = lower('{shadow}');"
        )

    section("2. Reddit handles claimed by more than one account")
    rows = q(cur, """
        SELECT lower(reddit_username), COUNT(*)
        FROM user_roles
        WHERE reddit_username IS NOT NULL AND reddit_username <> ''
        GROUP BY lower(reddit_username)
        HAVING COUNT(*) > 1
    """)
    if not rows:
        print("  none")
    for handle, count in rows:
        findings += 1
        print(f"  u/{handle} is linked to {count} accounts — bot commands from this "
              f"handle will be refused until a mod removes the duplicate")

    section("3. Verified lenders whose loans are split across two names")
    rows = q(cur, """
        SELECT ur.username, ur.reddit_username,
               SUM(CASE WHEN lower(l.lender) = lower(ur.username) THEN 1 ELSE 0 END),
               SUM(CASE WHEN lower(l.lender) = lower(ur.reddit_username) THEN 1 ELSE 0 END)
        FROM user_roles ur
        JOIN loans l
          ON lower(l.lender) IN (lower(ur.username), lower(ur.reddit_username))
        WHERE ur.reddit_username IS NOT NULL
          AND lower(ur.reddit_username) <> lower(ur.username)
        GROUP BY ur.username, ur.reddit_username
    """)
    split = [r for r in rows if r[2] and r[3]]
    if not split:
        print("  none")
    for dash, handle, as_dash, as_handle in split:
        findings += 1
        print(f"  '{dash}' has {as_dash} loans under the dashboard name and "
              f"{as_handle} under u/{handle} — the bot now reads both, but "
              f"aggregate stats in `users` are split")

    section("4. Split rows in the users stats table")
    rows = q(cur, """
        SELECT ur.username, ur.reddit_username
        FROM user_roles ur
        JOIN users a ON lower(a.username) = lower(ur.username)
        JOIN users b ON lower(b.username) = lower(ur.reddit_username)
        WHERE ur.reddit_username IS NOT NULL
          AND lower(ur.reddit_username) <> lower(ur.username)
    """)
    if not rows:
        print("  none")
    for dash, handle in rows:
        findings += 1
        print(f"  stats exist under both '{dash}' and '{handle}' — totals shown to "
              f"users are understated until these are merged")

    section("5. Loans whose lender has no user_roles record at all")
    rows = q(cur, """
        SELECT DISTINCT l.lender
        FROM loans l
        LEFT JOIN user_roles ur
          ON lower(ur.username) = lower(l.lender)
          OR lower(ur.reddit_username) = lower(l.lender)
        WHERE ur.username IS NULL
        ORDER BY l.lender
    """)
    if not rows:
        print("  none")
    for (lender,) in rows:
        print(f"  '{lender}' (bot-only account — fine unless they need the dashboard)")

    print()
    print("=" * 60)
    print(f"{findings} problem(s) needing attention.")
    if suggested:
        print("\nSuggested SQL — review each line before running it:\n")
        for stmt in suggested:
            print(stmt)
    print("\nThis script made no changes.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
