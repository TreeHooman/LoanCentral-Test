import re
import logging

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$unpaid"


DASHBOARD_URL = "https://loancentral.app"


def process_unpaid_command(comment):
    """
    $unpaid [loan_id]
    Lender marks a loan as unpaid. Borrower is looked up from the loan record.
    """
    from services import mark_unpaid, update_last_login

    match = re.search(r'\$unpaid\s+([\w-]+)', comment.body, re.IGNORECASE)
    if not match:
        return

    loan_id = match.group(1)
    lender = comment.author.name.lower()
    update_last_login(lender)

    result, error = mark_unpaid(loan_id, lender)

    if error:
        comment.reply(f"Error: {error}")
        return

    borrower = result["borrower"]
    current_subreddit = comment.subreddit.display_name

    response = (
        f"⚠ Loan `{loan_id}` marked **unpaid** — u/{borrower} owes u/{lender} "
        f"{result['loan_amount']:.2f} {result['currency']}\n\n"
        f"u/{borrower} — if this is incorrect, reply with `$dispute {loan_id}`\n\n"
        f"*[Dashboard]({DASHBOARD_URL})*"
    )

    comment.reply(response)
    logger.info(f"Loan {loan_id} marked unpaid by {lender}")
