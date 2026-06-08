"""
$dispute [loan_id]
Borrower flags a loan for mod review. Puts the loan into 'disputed' status.
"""

from bot_messages import DASHBOARD_URL, with_dashboard_link
from services import dispute_loan, update_last_login


def handle_dispute(comment, username):
    """
    Parse and handle a $dispute command.
    Format: $dispute [loan_id]
    """
    parts = comment.body.strip().split()

    # Need: $dispute <loan_id>
    if len(parts) < 2:
        return

    loan_id = parts[1].strip()

    # Auto-create user record on first interaction
    update_last_login(username)

    result, error = dispute_loan(loan_id, username)

    if error:
        comment.reply(with_dashboard_link(
            f"u/{username} - couldn't flag that dispute:\n\n"
            f"> {error}\n\n"
            f"Check your loan ID and try again, or visit {DASHBOARD_URL} to view your loans."
        ))
        return

    comment.reply(with_dashboard_link(
        f"u/{username} - Loan **{loan_id}** has been flagged as **disputed** and is now in the mod review queue.\n\n"
        f"A mod will review and reach out. In the meantime the loan status is frozen.\n\n"
        f"View your loan history: {DASHBOARD_URL}"
    ))
