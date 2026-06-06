import re
import logging
from decimal import Decimal

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$loan"


def process_loan_command(comment):
    """Process $loan command - announces a loan offer, borrower must confirm."""
    match = re.search(r'\$loan\s+(\d+(?:\.\d+)?)\s+([A-Z]{3})', comment.body, re.IGNORECASE)
    if not match:
        return

    lender = comment.author.name.lower()
    subreddit = comment.subreddit

    # Only verified lenders can issue loans
    try:
        user_flair = None
        for flair in subreddit.flair(redditor=comment.author):
            user_flair = flair['flair_text']
            break

        if not user_flair or 'verified lender' not in user_flair.lower():
            comment.reply(f"Error: Only users with 'Verified Lender' flair can issue loans in r/{subreddit.display_name}.")
            return

    except Exception as e:
        logger.error(f"Error checking flair for user {lender}: {e}")
        comment.reply("Error: Unable to verify your flair status. Please contact the moderators.")
        return

    amount = Decimal(match.group(1))
    currency = match.group(2).upper()
    borrower = comment.submission.author.name.lower()

    if amount <= 0:
        comment.reply("Error: Loan amount must be greater than zero.")
        return

    if borrower == lender:
        logger.warning(f"User {lender} attempted to lend to themselves")
        return

    comment.reply(
        f"I've seen that u/{lender} is offering {amount:.2f} {currency} to u/{borrower}!\n\n"
        f"u/{borrower} needs to confirm this transaction using:\n\n"
        f"```\n$confirm /u/{lender} {amount:.2f} {currency}\n```\n\n"
        f"The loan will only be registered in the database after confirmation."
    )
    logger.info(f"Loan offer: {lender} offering {amount} {currency} to {borrower}")
