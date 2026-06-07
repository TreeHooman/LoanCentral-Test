"""
LoanCentral SMS Reminder Job
-----------------------------
Run daily via Render cron (or: python reminders.py).
  python reminders.py           -- one-shot
  python reminders.py --loop    -- runs every REMINDER_INTERVAL_SECONDS (default 3600)

Required env vars (all optional if SMS is not configured):
  TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM
  DASHBOARD_URL
"""

import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("LoanCentral.Reminders")

DASHBOARD_URL    = os.getenv("DASHBOARD_URL", "https://your-app.onrender.com")
_LOOP_INTERVAL   = int(os.getenv("REMINDER_INTERVAL_SECONDS", "3600"))


def _build_periodic_message(loan: dict) -> str:
    amount  = f"{loan['amount']:.2f} {loan['currency']}"
    lender  = f"u/{loan['lender']}"
    if loan.get("reminder_type") == "unpaid":
        return (
            f"LoanCentral URGENT: Your loan of {amount} from {lender} "
            f"(#{loan['loan_id']}) is marked UNPAID. "
            f"Contact your lender to resolve. Dashboard: {DASHBOARD_URL}"
        )
    return (
        f"LoanCentral reminder: You have an outstanding loan of {amount} from {lender} "
        f"(#{loan['loan_id']}). Please arrange repayment. Dashboard: {DASHBOARD_URL}"
    )


def run_once():
    from services import get_loans_for_reminder, mark_reminder_sent, send_due_reminders
    from notifications import send_sms

    # Periodic reminders: overdue/active loans, unpaid loans
    loans, error = get_loans_for_reminder()
    if error:
        logger.error(f"Could not fetch reminder loans: {error}")
    else:
        periodic_sent = 0
        for loan in loans:
            try:
                msg = _build_periodic_message(loan)
                send_sms(loan["phone"], msg)
                mark_reminder_sent(loan["db_id"])
                periodic_sent += 1
                logger.info(f"Periodic SMS sent: loan #{loan['loan_id']} -> u/{loan['borrower']}")
            except Exception as e:
                logger.error(f"Periodic reminder failed for loan {loan['loan_id']}: {e}")
        logger.info(f"Periodic reminders: {periodic_sent}/{len(loans)} sent")

    # Due-date reminders: loans due within 3 days
    due_count, due_error = send_due_reminders()
    if due_error:
        logger.error(f"Due-date reminders failed: {due_error}")
    else:
        logger.info(f"Due-date reminders: {due_count} sent")


def main():
    if "--loop" in sys.argv:
        logger.info(f"Reminder loop started (interval: {_LOOP_INTERVAL}s)")
        while True:
            try:
                run_once()
            except Exception as e:
                logger.error(f"Reminder run error: {e}", exc_info=True)
            time.sleep(_LOOP_INTERVAL)
    else:
        logger.info("Starting reminder job...")
        run_once()
        logger.info("Reminder job complete.")


if __name__ == "__main__":
    main()
