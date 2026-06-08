"""
$dispute [loan_id]
Borrower flags a loan for mod review. Puts the loan into 'disputed' status.
"""
import logging

from bot_messages import DASHBOARD_URL, with_dashboard_link
from services import dispute_loan, update_last_login

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$dispute"


def process_dispute_command(comment):
    parts = comment.body.strip().split()
    if len(parts) < 2:
        return

    loan_id = parts[1].strip()
    username = comment.author.name.lower()

    update_last_login(username)

    result, error = dispute_loan(loan_id, username)

    if error:
        comment.reply(with_dashboard_link(
            f"Error: {error}\n\n"
            f"Check your loan ID and try again, or view your loans at [{DASHBOARD_URL}]({DASHBOARD_URL})."
        ))
        logger.warning(f"Dispute failed for loan {loan_id} by {username}: {error}")
        return

    comment.reply(with_dashboard_link(
        f"Loan **{loan_id}** has been flagged as **disputed** and queued for mod review.\n\n"
        f"|Loan ID|Borrower|Status|\n"
        f"|:--:|:--:|:--:|\n"
        f"|`{loan_id}`|u/{username}|Disputed|\n\n"
        f"The loan is now frozen while mods review. "
        f"A mod will follow up. View your record at [{DASHBOARD_URL}]({DASHBOARD_URL})."
    ))
    logger.info(f"Loan {loan_id} disputed by {username}")


# backwards-compat alias used by tests
def handle_dispute(comment, username):
    process_dispute_command(comment)
