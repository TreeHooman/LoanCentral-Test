"""
LoanCentral SMS Reminder Job
-----------------------------
Run daily via Render cron (or manually: python reminders.py).
Sends Twilio SMS to borrowers with:
  - Active loans older than 7 days (reminder every 7 days)
  - Unpaid loans (reminder every 3 days)

Required env vars:
  TWILIO_ACCOUNT_SID
  TWILIO_AUTH_TOKEN
  TWILIO_FROM_NUMBER   (your Twilio phone number, e.g. +15551234567)
  DASHBOARD_URL        (linked in the message)
"""

import logging
import os
import sys
from datetime import datetime
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

DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://your-app.onrender.com")
TWILIO_SID    = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM   = os.getenv("TWILIO_FROM_NUMBER", "")


def _twilio_client():
    if not all([TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM]):
        raise RuntimeError(
            "Twilio not configured. Set TWILIO_ACCOUNT_SID, "
            "TWILIO_AUTH_TOKEN, and TWILIO_FROM_NUMBER."
        )
    from twilio.rest import Client
    return Client(TWILIO_SID, TWILIO_TOKEN)


def _build_message(loan: dict) -> str:
    amount   = f"${loan['amount']:.2f} {loan['currency']}"
    lender   = f"u/{loan['lender']}"
    borrower = f"u/{loan['borrower']}"

    if loan["status"] == "unpaid":
        return (
            f"LoanCentral URGENT: Your loan of {amount} from {lender} "
            f"has been marked UNPAID. Please contact your lender to resolve this. "
            f"Dashboard: {DASHBOARD_URL} "
            f"Reply STOP to unsubscribe."
        )

    days_old = (datetime.utcnow() - loan["date_created"]).days if loan["date_created"] else "?"
    return (
        f"LoanCentral reminder: {borrower}, you have an active loan of "
        f"{amount} from {lender} ({days_old} days ago). "
        f"Please update your repayment status: {DASHBOARD_URL} "
        f"Reply STOP to unsubscribe."
    )


def send_reminders():
    from services import get_loans_for_reminder, mark_reminder_sent

    loans, error = get_loans_for_reminder()
    if error:
        logger.error(f"Failed to fetch loans: {error}")
        return

    if not loans:
        logger.info("No loans need reminders today.")
        return

    try:
        client = _twilio_client()
    except RuntimeError as e:
        logger.error(str(e))
        return

    sent = 0
    failed = 0
    for loan in loans:
        try:
            msg = _build_message(loan)
            client.messages.create(
                body=msg,
                from_=TWILIO_FROM,
                to=loan["phone"],
            )
            mark_reminder_sent(loan["db_id"])
            logger.info(
                f"SMS sent to {loan['borrower']} ({loan['phone']}) "
                f"for loan {loan['loan_id']} [{loan['status']}]"
            )
            sent += 1
        except Exception as e:
            logger.error(
                f"Failed to send SMS to {loan['borrower']} "
                f"for loan {loan['loan_id']}: {e}"
            )
            failed += 1

    logger.info(f"Reminders done. Sent: {sent}, Failed: {failed}, Total: {len(loans)}")


if __name__ == "__main__":
    logger.info("Starting reminder job...")
    send_reminders()
    logger.info("Reminder job complete.")
