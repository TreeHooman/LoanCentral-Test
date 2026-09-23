"""
Launch-day bootstrap: give the first people their roles.

The original bot's database has only `loans` and `users`. After migrating,
`user_roles` is empty: no admin, no moderator, no verified lender. Production
has no dev login, and login keys are issued by an admin from the dashboard, so
without this script nobody could sign in to fix that.

Everything goes through the normal service functions, so each change is
audited exactly as if an admin had made it on the dashboard.

    # see who has lent before, to decide who to verify
    python scripts/bootstrap_roles.py --list-lenders

    # preview (default) — shows what would change, changes nothing
    python scripts/bootstrap_roles.py --admin YOURNAME --lender alice --lender bob

    # apply, and print a one-time login key for the admin
    python scripts/bootstrap_roles.py --admin YOURNAME --lender alice --apply --issue-admin-key

    # many lenders: one Reddit username per line
    python scripts/bootstrap_roles.py --lenders-file verified.txt --apply

The admin login key is printed ONCE. Copy it somewhere safe; it cannot be
shown again (only its hash is stored). Further keys and lender verification
can then be managed from the dashboard.
"""

import argparse
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

USERNAME = re.compile(r"^[a-z0-9_-]{2,40}$")
ACTOR = "launch-bootstrap"


def clean(name):
    name = (name or "").strip().lower()
    if name.startswith("u/"):
        name = name[2:]
    return name


def read_names(values, path):
    names = [clean(v) for v in values or []]
    if path:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0]
            if line.strip():
                names.append(clean(line))
    bad = [n for n in names if not USERNAME.match(n)]
    if bad:
        raise SystemExit(f"Not valid Reddit usernames: {', '.join(bad)}")
    return sorted(set(names))


def list_lenders():
    from services import _get_db
    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT lower(lender), COUNT(*),
                   SUM(CASE WHEN status = 'repaid' THEN 1 ELSE 0 END),
                   MAX(date_created)
            FROM loans GROUP BY lower(lender) ORDER BY COUNT(*) DESC
        """)
        rows = cur.fetchall() or []
    finally:
        cur.close()
        conn.close()
    print(f"{'lender':28s} {'loans':>6s} {'repaid':>7s}  last loan")
    for name, count, repaid, last in rows:
        print(f"{name:28s} {count:>6d} {int(repaid or 0):>7d}  {str(last)[:10]}")
    print(f"\n{len(rows)} distinct lender(s) in the loan history.")


def current_roles(names):
    from services import get_user_role, get_verified_lender_status
    state = {}
    for name in names:
        role, _ = get_user_role(name)
        verified, _, _ = get_verified_lender_status(name)
        state[name] = (role, verified)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--admin", action="append", default=[], help="make this user an admin")
    parser.add_argument("--mod", action="append", default=[], help="make this user a moderator")
    parser.add_argument("--lender", action="append", default=[], help="mark as verified lender")
    parser.add_argument("--lenders-file", help="file of usernames to verify, one per line")
    parser.add_argument("--list-lenders", action="store_true",
                        help="show everyone who has lent, then exit")
    parser.add_argument("--apply", action="store_true", help="make the changes (default: preview)")
    parser.add_argument("--issue-admin-key", action="store_true",
                        help="with --apply: print a one-time login key for each admin")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")

    if args.list_lenders:
        list_lenders()
        return 0

    admins = read_names(args.admin, None)
    mods = [n for n in read_names(args.mod, None) if n not in admins]
    lenders = read_names(args.lender, args.lenders_file)
    if not (admins or mods or lenders):
        parser.print_help()
        return 2

    everyone = sorted(set(admins) | set(mods) | set(lenders))
    before = current_roles(everyone)

    print("Planned changes:")
    for name in everyone:
        role, verified = before[name]
        target = "admin" if name in admins else "mod" if name in mods else (role or "lender")
        marks = []
        if target != role:
            marks.append(f"role {role or '(none)'} -> {target}")
        if name in lenders and not verified:
            marks.append("verified lender: no -> yes")
        print(f"  u/{name:26s} {'; '.join(marks) or 'no change'}")

    if not args.apply:
        print("\nPreview only. Re-run with --apply to make these changes.")
        return 0

    from services import create_lender_key, set_user_role, set_verified_lender

    failures = 0
    for name in everyone:
        role, verified = before[name]
        target = "admin" if name in admins else "mod" if name in mods else None
        if target and target != role:
            ok, error = set_user_role(name, target, actor=ACTOR, actor_role="admin")
            if error:
                print(f"  FAILED role for u/{name}: {error}")
                failures += 1
        if name in lenders and not verified:
            ok, error = set_verified_lender(name, True, ACTOR, "Verified at launch (bootstrap)")
            if error:
                print(f"  FAILED verification for u/{name}: {error}")
                failures += 1

    after = current_roles(everyone)
    print("\nNow:")
    for name in everyone:
        role, verified = after[name]
        print(f"  u/{name:26s} role={role or '(none)':9s} verified_lender={'yes' if verified else 'no'}")

    if args.issue_admin_key:
        for name in admins:
            key, error = create_lender_key(name, ACTOR, label="launch bootstrap")
            if error:
                print(f"\n  FAILED to issue a key for u/{name}: {error}")
                failures += 1
                continue
            print(f"\n  Login key for u/{name} — shown ONCE, copy it now:\n\n      {key}\n")
            print("  Sign in at /login with 'Login with Key'.")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
