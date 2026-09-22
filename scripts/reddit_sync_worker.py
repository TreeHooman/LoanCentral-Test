"""
Drain the queued Reddit actions produced by funding a loan.

Dry-run by default. Reporting what it would do requires nothing; actually
posting to Reddit requires --live, which exists so that docs/SECURITY.md rule 4
("no live Reddit API writes unless explicitly marked safe") is satisfied by the
command line rather than by remembering to set something.

    python scripts/reddit_sync_worker.py                 # show what is pending
    python scripts/reddit_sync_worker.py --failures      # show what needs a human
    python scripts/reddit_sync_worker.py --live          # actually sync (one pass)
    python scripts/reddit_sync_worker.py --live --limit 5

The loan is already committed before anything reaches this queue, so nothing
here can change loan state. A failed action is retried with backoff and, after
REDDIT_SYNC_MAX_ATTEMPTS, left as 'failed' for review.
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true",
                        help="actually send to Reddit (default: dry run)")
    parser.add_argument("--limit", type=int, default=25,
                        help="maximum actions to process in this pass")
    parser.add_argument("--failures", action="store_true",
                        help="list actions that need a human, then exit")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")

    import reddit_sync

    if args.failures:
        rows, error = reddit_sync.sync_failures()
        if error:
            print(f"Could not read sync failures: {error}")
            return 1
        if not rows:
            print("No failed or skipped Reddit actions.")
            return 0
        print(f"{len(rows)} action(s) needing attention:\n")
        for row in rows:
            print(f"  [{row['status']:8s}] #{row['id']} {row['action_type']} "
                  f"request={row['request_id']} loan={row['loan_id']} "
                  f"attempts={row['attempts']}")
            if row["last_error"]:
                print(f"              {row['last_error']}")
        return 0

    summary, error = reddit_sync.run_once(limit=args.limit, live=args.live)
    if error:
        print(f"Sync pass failed: {error}")
        return 1

    if not args.live:
        print(f"DRY RUN — {summary['considered']} action(s) due, nothing sent.")
        for planned in summary["planned"]:
            print(f"  would {planned['action_type']}: request={planned['request_id']} "
                  f"loan={planned['loan_id']}")
        if summary["considered"]:
            print("\nRe-run with --live to send these.")
        return 0

    print(f"Considered {summary['considered']}: "
          f"{summary['sent']} sent, {summary['failed']} failed, "
          f"{summary['skipped']} skipped, {summary['unsupported']} unsupported.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
