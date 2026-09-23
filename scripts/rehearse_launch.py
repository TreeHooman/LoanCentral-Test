"""
Launch rehearsal against a RESTORED COPY of the live database.

Restore a backup into a local Postgres database whose name contains
"rehearsal", point DB_HOST/DB_PORT/DB_NAME at it, run the launch steps
(bot startup, migrations, bootstrap_roles.py), then run this. It exercises the
application end to end on real PostgreSQL — the one thing the test suite, which
runs on SQLite, cannot do.

It WRITES test data (a request, a loan, a ban), which is why it refuses to run
unless the database is on localhost and named *rehearsal*. Reddit is never
contacted: REDDIT_MODE must be dry_run, and the sync worker is driven with a
fake client.

    python scripts/rehearse_launch.py --lender logistix1 --admin YOURNAME

Checks, in order:
  1. a [REQ] post through the real bot entry point becomes a request
  2. a verified lender signs in with a LOGIN KEY (the production path)
  3. the lender funds the request by code from the dashboard
  4. the lender records the repayment
  5. every GET page, as admin, returns no 5xx on Postgres
  6. a moderator bans and unbans a user; the ban locks them out
  7. the Reddit sync queue drains through the worker with a fake client
  8. the ORIGINAL bot's SQL still works on the migrated schema (rollback)
  9. the read-only integrity check runs
"""

import argparse
import os
import re
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RESULTS = []


def check(name):
    def wrap(fn):
        def run(*a, **k):
            try:
                detail = fn(*a, **k)
                RESULTS.append((True, name, detail or ""))
                print(f"  PASS  {name}" + (f" — {detail}" if detail else ""))
            except Exception as e:
                RESULTS.append((False, name, str(e)))
                print(f"  FAIL  {name} — {e}")
                if os.getenv("REHEARSAL_VERBOSE"):
                    traceback.print_exc()
        return run
    return wrap


def refuse_unless_rehearsal():
    host = (os.getenv("DB_HOST") or "").strip()
    name = (os.getenv("DB_NAME") or "").strip()
    if os.getenv("DATABASE_URL", "").strip():
        raise SystemExit("Refusing: DATABASE_URL is set. Unset it and use DB_HOST/DB_NAME.")
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit(f"Refusing: DB_HOST={host!r} is not local.")
    if "rehearsal" not in name.lower():
        raise SystemExit(f"Refusing: DB_NAME={name!r} does not contain 'rehearsal'.")
    if (os.getenv("REDDIT_MODE") or "").lower() not in ("dry_run", "dry-run", "dryrun", "off"):
        raise SystemExit("Refusing: set REDDIT_MODE=dry_run.")
    if (os.getenv("DB_BACKEND") or "").lower() == "sqlite":
        raise SystemExit("Refusing: DB_BACKEND=sqlite — this rehearses Postgres.")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lender", required=True, help="a lender already verified by bootstrap_roles.py")
    parser.add_argument("--admin", required=True, help="an admin created by bootstrap_roles.py")
    args = parser.parse_args()

    refuse_unless_rehearsal()
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")          # never overrides the variables checked above
    refuse_unless_rehearsal()

    import utils
    conn = utils.get_db_connection()
    if getattr(conn, "is_sqlite", False):
        raise SystemExit("Refusing: connected to SQLite, not the rehearsal Postgres.")
    cur = conn.cursor()
    cur.execute("SELECT current_database(), inet_server_addr()")
    database, addr = cur.fetchone()
    conn.close()
    if "rehearsal" not in database or str(addr) not in ("127.0.0.1", "::1"):
        raise SystemExit(f"Refusing: connected to {database}@{addr}.")
    if type(utils.reddit).__name__ != "DryRunReddit":
        raise SystemExit("Refusing: the Reddit client is not the dry-run stub.")
    print(f"Rehearsing against {database} on {addr} (Postgres). Reddit: dry-run stub.\n")

    import services
    import main as bot
    os.environ["LOANCENTRAL_ENV"] = "prod"      # production app behaviour
    import importlib
    web = importlib.import_module("api.app")
    web.app.config.update(TESTING=True)
    def https_client():
        # Production marks the session cookie Secure, so the client must speak
        # HTTPS or it would silently drop the session between requests.
        c = web.app.test_client()
        c.environ_base["wsgi.url_scheme"] = "https"
        return c

    client = https_client()

    lender, admin = args.lender.lower(), args.admin.lower()
    stamp = str(int(time.time()))
    borrower = f"rehearsal_borrower_{stamp}"
    post_id = f"rh{stamp}"
    state = {}

    def query(sql, params=()):
        c = utils.get_db_connection()
        try:
            k = c.cursor()
            k.execute(sql, params)
            try:
                rows = k.fetchall()
            except Exception:
                rows = []
            c.commit()
            return rows
        finally:
            c.close()

    # 1 ----------------------------------------------------------------------
    @check("bot imports a [REQ] post")
    def step1():
        class Author:
            name = borrower

        class Reply:
            id = f"bot{stamp}"

        class Post:
            id = post_id
            title = f"[REQ] ($150) (#Rehearsal, ST, USA) (Repay $180) (12/31)"
            author = Author()
            permalink = f"/r/rehearsal/comments/{post_id}/x/"
            created_utc = time.time()
            replies = []

            def reply(self, body):
                self.replies.append(body)
                return Reply()

        post = Post()
        bot.handle_new_post(post)
        rows = query("SELECT request_id, request_status, reddit_comment_id "
                     "FROM loan_requests WHERE reddit_post_id = %s", (post_id,))
        assert rows, "no request row was created"
        state["request_id"] = rows[0][0]
        assert rows[0][1] == "open", rows[0]
        assert rows[0][2] == f"bot{stamp}", "bot comment id not stored"
        assert len(post.replies) == 1, "expected exactly one bot reply"
        return state["request_id"]
    step1()

    # 2 ----------------------------------------------------------------------
    @check("lender signs in with a login key")
    def step2():
        key, error = services.create_lender_key(lender, "rehearsal", label="rehearsal")
        assert not error, error
        r = client.post("/auth/key", headers={"X-API-Key": key})
        assert r.status_code == 200, r.get_json()
        r = client.get("/dashboard/lender")
        assert r.status_code == 200, f"lender dashboard -> {r.status_code}"
        return "production key login path"
    step2()

    # 3 ----------------------------------------------------------------------
    @check("lender funds the request from the dashboard")
    def step3():
        rid = state["request_id"]
        r = client.post(f"/api/requests/{rid}/fund",
                        json={"repay_amount": "180.00", "repay_date": "2027-12-31"})
        assert r.status_code == 200, r.get_json()
        state["loan_id"] = r.get_json()["loan_id"]
        status = query("SELECT request_status FROM loan_requests WHERE request_id = %s", (rid,))[0][0]
        assert status == "funded", status
        events = [e[0] for e in query(
            "SELECT event_type FROM request_events WHERE request_id = %s ORDER BY id", (rid,))]
        assert events == ["created", "funded"], events
        queued = {q[0] for q in query(
            "SELECT action_type FROM reddit_actions WHERE request_id = %s", (rid,))}
        assert queued == {"flair_sync", "funded_comment"}, queued
        return f"loan {state['loan_id']}; timeline + sync queue written"
    step3()

    # 4 ----------------------------------------------------------------------
    @check("lender records the repayment")
    def step4():
        r = client.post(f"/api/loans/{state['loan_id']}/paid",
                        json={"amount": "180.00", "currency": "USD", "timing": "on_time"})
        assert r.status_code == 200, r.get_json()
        status = query("SELECT status, payment_timing FROM loans WHERE loan_id = %s",
                       (state["loan_id"],))[0]
        assert status == ("repaid", "on_time"), status
        return "repaid, on_time"
    step4()

    # 5 ----------------------------------------------------------------------
    @check("every GET page responds without 5xx (as admin)")
    def step5():
        with client.session_transaction() as s:
            s.clear()
            s["username"], s["role"] = admin, "admin"
        subs = {"loan_id": state["loan_id"], "request_id": state["request_id"],
                "username": lender, "token": "x", "key_id": "1", "att_id": "1",
                "action_id": "1", "application_id": "1", "feedback_id": "1",
                "note_id": "1", "announcement_id": "1"}
        skip = {"/auth/logout", "/auth/reddit", "/auth/callback"}
        failures, count = [], 0
        for rule in web.app.url_map.iter_rules():
            if "GET" not in rule.methods or rule.rule.startswith("/static") or rule.rule in skip:
                continue
            path = rule.rule
            for arg in re.findall(r"<([^>]+)>", rule.rule):
                value = subs.get(arg.split(":")[-1])
                if value is None:
                    path = None
                    break
                path = path.replace(f"<{arg}>", str(value))
            if not path:
                continue
            count += 1
            r = client.get(path)
            if r.status_code >= 500:
                failures.append(f"{path} -> {r.status_code}: {r.get_data(as_text=True)[:120]}")
        assert not failures, "; ".join(failures)
        return f"{count} pages"
    step5()

    # 6 ----------------------------------------------------------------------
    @check("moderator bans and unbans; the ban locks the user out")
    def step6():
        r = client.post(f"/api/admin/bans/{borrower}", json={"reason": "rehearsal"})
        assert r.status_code == 200, r.get_json()
        banned, _ = services.is_user_banned(borrower)
        assert banned
        other = https_client()
        with other.session_transaction() as s:
            s["username"], s["role"] = borrower, "borrower"
        r = other.get("/api/users/me")
        assert r.status_code == 403, f"banned user got {r.status_code}"
        r = client.delete(f"/api/admin/bans/{borrower}", json={"reason": "rehearsal done"})
        assert r.status_code == 200, r.get_json()
        assert not services.is_user_banned(borrower)[0]
        return "ban enforced, then lifted"
    step6()

    # 7 ----------------------------------------------------------------------
    @check("Reddit sync drains through the worker (fake client)")
    def step7():
        import reddit_sync

        class Comment:
            body = "original"

            def edit(self, body):
                self.body = body

        class Mod:
            def flair(self, text=None, **_):
                state["flair"] = text

        class Submission:
            mod = Mod()

        class FakeReddit:
            comment_obj = Comment()

            def submission(self, id=None):
                return Submission()

            def comment(self, id=None):
                return self.comment_obj

        fake = FakeReddit()
        # Only this rehearsal's actions: leave anything else in the queue alone.
        others = query("SELECT id FROM reddit_actions WHERE status = 'queued' "
                       "AND COALESCE(request_id, '') <> %s", (state["request_id"],))
        ids = [o[0] for o in others]
        if ids:
            query("UPDATE reddit_actions SET next_attempt_at = %s WHERE id IN ("
                  + ",".join(["%s"] * len(ids)) + ")", ["2999-01-01", *ids])
        try:
            summary, error = reddit_sync.run_once(live=True, reddit=fake)
        finally:
            if ids:
                query("UPDATE reddit_actions SET next_attempt_at = NULL WHERE id IN ("
                      + ",".join(["%s"] * len(ids)) + ")", ids)
        assert not error, error
        assert summary["sent"] == 2, summary
        assert "Funded by u/" + lender in fake.comment_obj.body
        return f"flair set to {state['flair']!r}, comment edited"
    step7()

    # 8 ----------------------------------------------------------------------
    @check("original bot's SQL still works on the migrated schema (rollback)")
    def step8():
        # The exact statements loan_central_bot.py issues, with its own values.
        old_id = f"9{stamp}"
        c = utils.get_db_connection()
        try:
            k = c.cursor()
            k.execute("""
                INSERT INTO loans
                (loan_id, lender, borrower, amount, currency, date_created, original_thread, status)
                VALUES (%s, %s, %s, %s, %s, NOW(), %s, %s) RETURNING id
            """, (old_id, "oldbot_lender", "oldbot_borrower", 50, "USD",
                  "https://example.com/rollback", "confirmed"))
            db_id = k.fetchone()[0]
            for new_status in ("partially_repaid", "unpaid", "refunded"):
                k.execute("UPDATE loans SET amount_repaid=%s, status=%s, last_updated=NOW() "
                          "WHERE id=%s", (10, new_status, db_id))
            k.execute("""
                INSERT INTO users (username, loans_as_lender, amount_lent, last_updated)
                VALUES (%s, 1, %s, NOW())
                ON CONFLICT (username) DO UPDATE SET loans_as_lender = users.loans_as_lender + 1
            """, ("oldbot_lender", 50))
            c.rollback()        # leave no trace
        finally:
            c.close()
        return "insert + status updates accepted (then rolled back)"
    step8()

    # 9 ----------------------------------------------------------------------
    @check("integrity check runs")
    def step9():
        import subprocess
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_db_integrity.py")],
                           capture_output=True, text=True, env=os.environ.copy())
        out = r.stdout + r.stderr
        assert "Integrity check" in out, out[-300:]
        problems = re.findall(r"^\s+X\s+(.*)$", out, re.M)
        return "clean" if not problems else "findings: " + "; ".join(problems)
    step9()

    passed = sum(1 for ok, _, _ in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} checks passed.")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
