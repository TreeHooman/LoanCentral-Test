import re
import logging
from decimal import Decimal

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$loan"


def process_loan_command(comment):
    """
    $loan [amount] [currency] u/[borrower]
    Lender records a loan immediately — no borrower confirmation needed.
    """
    from services import create_loan

    match = re.search(
        r'\$loan\s+(\d+(?:\.\d+)?)\s+([A-Z]{3})\s+u?/?([\w-]+)',
        comment.body,
        re.IGNORECASE,
    )
    if not match:
        return

    lender = comment.author.name.lower()
    amount = Decimal(match.group(1))
    currency = match.group(2).upper()
    borrower = match.group(3).lower()

    if lender == borrower:
        comment.reply("Error: You cannot lend to yourself.")
        return

    if amount <= 0:
        comment.reply("Error: Loan amount must be greater than zero.")
        return

    # Verify lender flair
    try:
        subreddit = comment.subreddit
        user_flair = None
        for flair in subreddit.flair(redditor=comment.author):
            user_flair = flair["flair_text"]
            break
        if not user_flair or "verified lender" not in user_flair.lower():
            comment.reply(
                f"Error: Only users with 'Verified Lender' flair can issue loans "
                f"in r/{subreddit.display_name}."
            )
            return
    except Exception as e:
        logger.error(f"Error checking flair for {lender}: {e}")
        comment.reply("Error: Unable to verify your flair status. Please contact the moderators.")
        return

    thread_url = f"https://www.reddit.com{comment.submission.permalink}"
    db_id, error = create_loan(lender, borrower, amount, currency, thread_url)

    if error:
        comment.reply(f"Error: {error}")
        return

    comment.reply(
        f"Loan recorded!\n\n"
        f"|Loan ID|Lender|Borrower|Amount|Currency|\n"
        f"|:--:|:--:|:--:|:--:|:--:|\n"
        f"|**{db_id}**|u/{lender}|u/{borrower}|{amount:.2f}|{currency}|\n\n"
        f"u/{borrower} — you have received **{amount:.2f} {currency}** from u/{lender}. "
        f"Use loan ID `{db_id}` for all future references to this loan.\n\n"
        f"**Lender commands:**\n"
        f"- Record repayment: `$paid_with_id {db_id} [amount] {currency}`\n"
        f"- Mark unpaid: `$unpaid {db_id}`\n"
        f"- Cancel loan: `$refunded {db_id}`"
    )
    logger.info(f"Loan created: {lender} -> {borrower} {amount} {currency} (db_id={db_id})")
