import logging
import re

from bot_messages import DASHBOARD_URL, with_dashboard_link
from commands.lender_gate import require_verified_lender

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$refunded"


def process_refund_command(comment):
    """
    $refunded [loan_id]
    Lender cancels a loan by ID. Reverses stats and notifies mods.
    """
    from services import mark_refunded_by_id, update_last_login

    match = re.search(r"\$refunded\s+(\w+)", comment.body, re.IGNORECASE)
    if not match:
        return

    loan_id = match.group(1)
    lender = comment.author.name.lower()
    if not require_verified_lender(comment):
        return
    update_last_login(lender)

    result, error = mark_refunded_by_id(loan_id, lender)

    if error:
        comment.reply(with_dashboard_link(f"Error: {error}"))
        return

    borrower = result["borrower"]
    amount = result["amount"]
    currency = result["currency"]

    try:
        from utils import reddit, reddit_limiter

        post_subreddit = comment.submission.subreddit.display_name
        reddit_limiter.wait()
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

    comment.reply(with_dashboard_link(
        f"Loan `{loan_id}` marked as refunded.\n\n"
        f"The loan from u/{lender} to u/{borrower} for {amount:.2f} {currency} "
        f"has been removed from both users' statistics.\n\n"
        f"---\n*View loan history at [{DASHBOARD_URL}]({DASHBOARD_URL})*"
    ))
    logger.info(f"Loan {loan_id} refunded: {lender} -> {borrower} {amount} {currency}")
