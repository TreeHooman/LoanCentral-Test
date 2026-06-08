"""
$dispute [loan_id]
Borrower flags a loan for mod review. Puts the loan into 'disputed' status.
"""

import logging

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$dispute"
DASHBOARD_URL = "https://loancentral.app"


def process_dispute_command(comment):
    """Parse and handle a $dispute command: $dispute [loan_id]"""
    from services import dispute_loan, update_last_login

    parts = comment.body.strip().split()
    if len(parts) < 2:
        return  # silent — no help spam

    loan_id = parts[1].strip()
    username = comment.author.name.lower()

    update_last_login(username)

    result, error = dispute_loan(loan_id, username)

    if error:
        comment.reply(
            f"u/{username} — couldn't flag that dispute:\n\n"
            f"> {error}\n\n"
            f"Check your loan ID and try again, or visit {DASHBOARD_URL} to view your loans."
        )
        return

    comment.reply(
        f"u/{username} — Loan **{loan_id}** has been flagged as **disputed** and is now in the mod review queue.\n\n"
        f"A mod will review and reach out. In the meantime the loan status is frozen.\n\n"
        f"View your loan history: {DASHBOARD_URL}"
    )
    logger.info(f"Loan {loan_id} disputed by {username}")
