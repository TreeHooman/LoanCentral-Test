"""
LoanCentral reminder job foundation.

Safe default: dry-run only. It reads due-date records and prints planned actions.
It does not call Reddit unless future live delivery code is explicitly added.

Run:
  python scripts/reminder_job.py
  python scripts/reminder_job.py --days 3 --json
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(".env.test", override=False)
os.environ.setdefault("LOANCENTRAL_ENV", "dev")
os.environ.setdefault("DB_BACKEND", "sqlite")

from api.app import app
from services import enqueue_reddit_action


def fetch_queue(days):
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["username"] = "reminder_job"
            sess["role"] = "mod"
        response = client.get(f"/api/reminders?days={days}&limit=500")
        if response.status_code != 200:
            raise RuntimeError(response.get_data(as_text=True))
        return response.get_json()


def planned_action(item):
    level = item.get("level")
    if level == "overdue":
        return "would_notify_lender_overdue"
    if level == "due_today":
        return "would_prepare_due_today_reminder"
    if level == "due_soon":
        return "would_prepare_due_soon_reminder"
    if level == "missing_due_date":
        return "would_flag_missing_due_date"
    return "would_watch"


def action_type_for_item(item):
    level = item.get("level")
    if level == "overdue":
        return "lender_dm"
    if level in ("due_today", "due_soon"):
        return "reminder_comment"
    return None


def main():
    parser = argparse.ArgumentParser(description="Dry-run LoanCentral reminder queue.")
    parser.add_argument("--days", type=int, default=3, help="Due-soon window in days.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument("--enqueue", action="store_true", help="Queue actions for mod review. Still does not call Reddit.")
    args = parser.parse_args()

    queue = fetch_queue(args.days)
    actions = []
    for item in queue.get("items", []):
        action = {
            "action": planned_action(item),
            "loan_id": item.get("loan_id"),
            "lender": item.get("lender"),
            "borrower": item.get("borrower"),
            "level": item.get("level"),
            "days_until_due": item.get("days_until_due"),
            "remaining": item.get("remaining"),
            "thread": item.get("thread"),
        }
        if args.enqueue:
            action_type = action_type_for_item(item)
            if action_type:
                queued, error = enqueue_reddit_action(
                    action_type,
                    target_user=item.get("lender") if action_type == "lender_dm" else item.get("borrower"),
                    loan_id=item.get("loan_id"),
                    subreddit=None,
                    payload={
                        "level": item.get("level"),
                        "borrower": item.get("borrower"),
                        "lender": item.get("lender"),
                        "remaining": item.get("remaining"),
                        "days_until_due": item.get("days_until_due"),
                        "thread": item.get("thread"),
                    },
                    reason=f"Reminder queue dry-run enqueue: {item.get('level')}",
                    created_by="reminder_job",
                )
                action["queued"] = queued if not error else None
                action["queue_error"] = error
        actions.append(action)

    result = {
        "dry_run": True,
        "enqueued": bool(args.enqueue),
        "generated_at": datetime.now().isoformat(),
        "window_days": args.days,
        "counts": queue.get("counts", {}),
        "actions": actions,
    }

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print("LoanCentral reminder dry-run")
    print(f"Generated: {result['generated_at']}")
    print(f"Window: {args.days} day(s)")
    print(f"Counts: {result['counts']}")
    if not actions:
        print("No reminder actions needed.")
        return
    for action in actions:
        due = action["days_until_due"]
        due_text = "missing due date" if due is None else f"{due} day(s)"
        print(
            f"- {action['action']}: loan {action['loan_id']} "
            f"u/{action['lender']} -> u/{action['borrower']} "
            f"({action['level']}, {due_text}, remaining {action['remaining']})"
        )


if __name__ == "__main__":
    main()
