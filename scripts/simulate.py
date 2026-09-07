"""
Local Reddit simulator for the LoanCentral bot.

Runs the REAL command dispatcher (main.CommandManager) and REAL services layer
against a local SQLite database, with Reddit replaced by the dry-run stub.
Nothing here can touch Reddit or the production Postgres database: the
simulator forces DB_BACKEND=sqlite and REDDIT_MODE=dry_run before any project
module is imported, which overrides whatever .env says (load_dotenv never
overwrites existing environment variables).

Usage:
    python scripts/simulate.py                     # interactive REPL
    python scripts/simulate.py scenario.txt        # run a scripted scenario
    python scripts/simulate.py --reset             # wipe the sim DB first
    python scripts/simulate.py --db path.sqlite3   # use a different sim DB

REPL / scenario grammar (one action per line, # starts a comment):
    u/alice: $loan 50 USD u/bob      comment by alice on the current thread
    post u/bob: [REQ] Need $50 ...   new post by bob (runs the REQ handler)
    verify u/alice                   grant DB verified-lender + Reddit flair
    link alice_dash u/alice          link a dashboard account to a Reddit handle
    flair u/alice off|on             toggle just the flair (test the dual gate)
    loans | users | requests         dump DB tables
    outbox                           show captured outbound Reddit actions
    help                             list bot triggers + simulator commands
    exit                             quit
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# --- Environment safety rails: MUST run before any project import ----------
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))
os.environ["DB_BACKEND"] = "sqlite"          # never Postgres, never prod
os.environ["REDDIT_MODE"] = "dry_run"        # never the live Reddit API
os.environ["LOANCENTRAL_ENV"] = "dev"
os.environ["BOT_COMMAND_COOLDOWN_SECONDS"] = "0"
os.environ.setdefault("SUBREDDITS", "LoanCentralSim")
DEFAULT_SIM_DB = PROJECT_ROOT / "data" / "loancentral_sim.sqlite3"


def _parse_args():
    parser = argparse.ArgumentParser(description="LoanCentral bot simulator (no Reddit, local SQLite)")
    parser.add_argument("scenario", nargs="?", help="scenario file to run instead of the interactive REPL")
    parser.add_argument("--db", default=str(DEFAULT_SIM_DB), help="path to the simulator SQLite database")
    parser.add_argument("--reset", action="store_true", help="delete the simulator database before starting")
    return parser.parse_args()


ARGS = _parse_args()
os.environ["SQLITE_DB_PATH"] = str(Path(ARGS.db).resolve())

if ARGS.reset:
    db_file = Path(os.environ["SQLITE_DB_PATH"])
    if db_file.exists():
        db_file.unlink()
        print(f"[sim] reset: deleted {db_file}")

# Project imports come only after the environment is pinned.
import main  # noqa: E402  (builds command_manager, loads all commands)
from tests.support.fakes import FakeSubreddit, FakeSubmission, FakeComment  # noqa: E402
from utils import get_db_connection, reddit  # noqa: E402


class SimSubreddit(FakeSubreddit):
    """Subreddit whose flair lookups honour the simulator's flair registry."""

    def __init__(self, display_name, flaired_users):
        super().__init__(display_name=display_name, flair_text=None)
        self._flaired_users = flaired_users

    def flair(self, redditor=None):
        if redditor and redditor.lower() in self._flaired_users:
            return [{"flair_text": "Verified Lender"}]
        return []


class SimSubmission(FakeSubmission):
    """Submission with the id/created_utc/reply surface handle_new_post needs."""

    def __init__(self, author_name, title, subreddit, post_id):
        super().__init__(
            author_name=author_name,
            subreddit=subreddit,
            permalink=f"/r/{subreddit.display_name}/comments/{post_id}/sim/",
            title=title,
        )
        self.id = post_id
        self.created_utc = time.time()
        self.replies = []

    def reply(self, body):
        self.replies.append(body)
        return body


class Simulator:
    def __init__(self):
        self.flaired_users = set()
        self.subreddit = SimSubreddit(os.environ["SUBREDDITS"].split(",")[0], self.flaired_users)
        self.post_counter = 0
        self.current_submission = self._new_submission("someone", "Simulator default thread")

    def _new_submission(self, author, title):
        self.post_counter += 1
        return SimSubmission(author, title, self.subreddit, f"simpost{self.post_counter}")

    # ----- actions ---------------------------------------------------------

    def do_comment(self, author, body):
        comment = FakeComment(
            body,
            author_name=author,
            submission=self.current_submission,
            subreddit=self.subreddit,
            created_utc=time.time(),
        )
        triggers = [t for t in main.command_manager.commands if t in body.lower()]
        main.command_manager.process_comment(comment)
        if comment.replies:
            for reply in comment.replies:
                self._print_reply(f"bot reply -> u/{author}", reply)
        elif triggers:
            print(f"  (bot matched {', '.join(triggers)} but did not reply - "
                  f"usually bad syntax; check LoanCentral.log)")
        else:
            print("  (no command trigger in that comment)")

    def do_post(self, author, title):
        submission = self._new_submission(author, title)
        self.current_submission = submission
        main.handle_new_post(submission)
        if submission.replies:
            for reply in submission.replies:
                self._print_reply(f"bot comment on post by u/{author}", reply)
        else:
            print("  (bot did not comment on the post)")

    def do_verify(self, username):
        from services import set_verified_lender

        ok, error = set_verified_lender(username, True, "simulator", "Verified via local simulator")
        if error:
            print(f"  error: {error}")
            return
        self.flaired_users.add(username.lower())
        print(f"  u/{username} is now DB-verified and has the Verified Lender flair")

    def do_link(self, dashboard_user, reddit_user):
        """Link a dashboard account to a different Reddit handle.

        Reproduces the real-world case where a lender signs up under one name
        and comments under another.
        """
        from services import link_reddit_username

        ok, error = link_reddit_username(dashboard_user, reddit_user, "simulator")
        if error:
            print(f"  error: {error}")
            return
        self.flaired_users.add(reddit_user.lower())
        print(f"  dashboard account '{dashboard_user}' is now linked to Reddit u/{reddit_user}")

    def do_flair(self, username, state):
        if state == "on":
            self.flaired_users.add(username.lower())
        else:
            self.flaired_users.discard(username.lower())
        print(f"  flair for u/{username}: {state}")

    def do_outbox(self):
        if not reddit.outbox:
            print("  (outbox empty - no outbound Reddit actions captured)")
            return
        for i, item in enumerate(reddit.outbox, 1):
            print(f"  [{i}] {item['type']} -> r/{item['subreddit']} | {item['subject']}")
            for line in item["message"].splitlines():
                print(f"      {line}")

    def dump_table(self, name):
        queries = {
            "loans": ("SELECT id, loan_id, lender, borrower, amount, amount_repaid, currency, status "
                      "FROM loans ORDER BY id",
                      ["id", "loan_id", "lender", "borrower", "amount", "repaid", "cur", "status"]),
            "users": ("SELECT username, loans_as_borrower, loans_as_lender, amount_borrowed, "
                      "amount_lent, amount_repaid, unpaid_loans FROM users ORDER BY username",
                      ["user", "as_borrower", "as_lender", "borrowed", "lent", "repaid", "unpaid"]),
            "requests": ("SELECT request_id, borrower_username, requested_amount, "
                         "requested_repayment_amount, request_status, funded_loan_id "
                         "FROM loan_requests ORDER BY id",
                         ["request_id", "borrower", "amount", "repay", "status", "funded_loan"]),
        }
        sql, headers = queries[name]
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute(sql)
            rows = cur.fetchall()
        finally:
            conn.close()
        if not rows:
            print(f"  ({name}: empty)")
            return
        table = [headers] + [[("" if v is None else str(v)) for v in row] for row in rows]
        widths = [max(len(r[i]) for r in table) for i in range(len(headers))]
        for row in table:
            print("  " + "  ".join(val.ljust(widths[i]) for i, val in enumerate(row)))

    # ----- plumbing --------------------------------------------------------

    @staticmethod
    def _print_reply(label, text):
        print(f"  [{label}]")
        for line in text.splitlines():
            print(f"    {line}")

    def print_help(self):
        print(__doc__.split("REPL / scenario grammar", 1)[1].split(":", 1)[1].rstrip())
        print("\n  Loaded bot triggers: " + ", ".join(sorted(main.command_manager.commands)))

    def handle_line(self, line):
        line = line.strip()
        if not line or line.startswith("#"):
            return True
        if line.lower() in ("exit", "quit"):
            return False
        if line.lower() == "help":
            self.print_help()
            return True
        if line.lower() in ("loans", "users", "requests"):
            self.dump_table(line.lower())
            return True
        if line.lower() == "outbox":
            self.do_outbox()
            return True

        m = re.match(r"^post\s+u/([\w-]+)\s*:\s*(.+)$", line, re.IGNORECASE)
        if m:
            self.do_post(m.group(1), m.group(2))
            return True

        m = re.match(r"^verify\s+u?/?([\w-]+)$", line, re.IGNORECASE)
        if m:
            self.do_verify(m.group(1))
            return True

        m = re.match(r"^link\s+([\w-]+)\s+u/([\w-]+)$", line, re.IGNORECASE)
        if m:
            self.do_link(m.group(1), m.group(2))
            return True

        m = re.match(r"^flair\s+u/([\w-]+)\s+(on|off)$", line, re.IGNORECASE)
        if m:
            self.do_flair(m.group(1), m.group(2).lower())
            return True

        m = re.match(r"^(?:as\s+)?u/([\w-]+)\s*:\s*(.+)$", line, re.IGNORECASE)
        if m:
            self.do_comment(m.group(1), m.group(2))
            return True

        print("  unrecognized line - type 'help' for the grammar")
        return True


def run():
    sim = Simulator()
    print(f"[sim] LoanCentral simulator | DB: {os.environ['SQLITE_DB_PATH']} | Reddit: dry-run stub")

    if ARGS.scenario:
        scenario_path = Path(ARGS.scenario)
        if not scenario_path.exists():
            sys.exit(f"[sim] scenario file not found: {scenario_path}")
        for raw in scenario_path.read_text(encoding="utf-8").splitlines():
            stripped = raw.strip()
            if not stripped:
                continue
            print(f"sim> {stripped}")
            if not sim.handle_line(stripped):
                break
        return

    print("[sim] type 'help' for commands, 'exit' to quit")
    while True:
        try:
            line = input("sim> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not sim.handle_line(line):
            break


if __name__ == "__main__":
    run()
