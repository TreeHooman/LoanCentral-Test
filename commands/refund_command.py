import re
import logging

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$refunded"


def process_refund_command(comment):
    """
    $refunded [loan_id]
    Lender cancels a loan by ID. Reverses stats and notifies mods.
    """
    from services import mark_refunded_by_id

    match = re.search(r'\$refunded\s+(\w+)', comment.body, re.IGNORECASE)
    if not match:
        return

    loan_id = match.group(1)
    lender = comment.author.name.lower()

    result, error = mark_refunded_by_id(loan_id, lender)

    if error:
        comment.reply(f"Error: {error}")
        return

    borrower = result["borrower"]
    amount = result["amount"]
    currency = result["currency"]

    # Notify moderators
    try:
        from utils import reddit
        post_subreddit = comment.submission.subreddit.display_name
        reddit.subreddit(post_subreddit).message(
            subject=f"Loan Refunded - {lender} to {borrower}",
            message=(
                f"A loan has been marked as refunded:\n\n"
                f"Lender: u/{lender}\nBorrower: u/{borrower}\n"
                f"Amount: {amount:.2f} {currency}\n"
                f"Loan ID: {loan_id}\n\n"
                f"Link: https://www.reddit.com{comment.permalink}"
            ),
        )
    except Exception as e:
        logger.error(f"Failed to notify mods of refund: {e}")

    from config import DASHBOARD_URL

    comment.reply(
        f"Loan `{loan_id}` marked as refunded.\n\n"
        f"The loan from u/{lender} to u/{borrower} for {amount:.2f} {currency} "
        f"has been removed from both users' statistics.\n\n"
        f"**[View updated stats on LoanCentral Dashboard]({DASHBOARD_URL})**"
    )
    logger.info(f"Loan {loan_id} refunded: {lender} -> {borrower} {amount} {currency}")
