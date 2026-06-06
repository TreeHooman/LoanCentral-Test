import re
import logging
from decimal import Decimal

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$refunded"


def process_refund_command(comment):
    """Process $refunded command - lender cancels a loan."""
    import os
    from services import mark_refunded

    # Must be a reply to the bot's confirmation comment
    parent = comment.parent()
    if not parent.author or parent.author.name.lower() != os.getenv("REDDIT_USERNAME", "").lower():
        return

    if "refunded" not in comment.body.lower():
        return

    # Extract loan details from the bot's confirmation comment
    match = re.search(
        r'u\/([^\s]+) has confirmed receiving (\d+(?:\.\d+)?)\s+([A-Z]{3}) from u\/([^\s\.]+)',
        parent.body
    )
    if not match:
        return

    borrower = match.group(1).lower()
    amount = Decimal(match.group(2))
    currency = match.group(3)
    lender = match.group(4).lower()

    # Only the lender can refund
    if comment.author.name.lower() != lender:
        comment.reply("Only the lender can mark a loan as refunded.")
        return

    result, error = mark_refunded(lender, borrower, amount, currency)

    if error:
        comment.reply(f"Error: {error}")
        return

    # Notify moderators
    try:
        from utils import reddit
        post_subreddit = comment.submission.subreddit.display_name
        reddit.subreddit(post_subreddit).message(
            subject=f"Loan Refunded - {lender} to {borrower}",
            message=(
                f"A loan has been marked as refunded:\n\n"
                f"Lender: u/{lender}\nBorrower: u/{borrower}\n"
                f"Amount: {amount:.2f} {currency}\n\n"
                f"Link: https://www.reddit.com{comment.permalink}"
            )
        )
    except Exception as e:
        logger.error(f"Failed to notify mods of refund: {e}")

    comment.reply(
        f"Loan marked as refunded. The loan from u/{lender} to u/{borrower} "
        f"for {amount:.2f} {currency} has been removed from both users' statistics."
    )
    logger.info(f"Loan refunded: {lender} -> {borrower} {amount} {currency}")
