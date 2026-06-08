import re
import logging
from decimal import Decimal

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$loan"
DASHBOARD_URL = "https://loancentral.app"  # update when domain is live


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

    from services import update_last_login
    update_last_login(lender)
    update_last_login(borrower)

    thread_url = f"https://www.reddit.com{comment.submission.permalink}"
    db_id, error = create_loan(lender, borrower, amount, currency, thread_url)

    if error:
        comment.reply(f"Error: {error}")
        return

    comment.reply(
        f"✓ Loan recorded — u/{borrower} owes u/{lender} **{amount:.2f} {currency}**\n\n"
        f"**Loan ID:** `{db_id}`\n\n"
        f"---\n\n"
        f"**u/{lender} — commands for this loan:**\n\n"
        f"    $paid {db_id} {amount:.2f} {currency}   ← full repayment\n"
        f"    $paid {db_id} [amount] {currency}        ← partial payment\n"
        f"    $unpaid {db_id}                          ← mark as unpaid\n"
        f"    $refunded {db_id}                        ← cancel loan\n\n"
        f"*u/{borrower} — to dispute this record: `$dispute {db_id}`*\n\n"
        f"*[Dashboard]({DASHBOARD_URL}) · [Help]({DASHBOARD_URL})*"
    )
    logger.info(f"Loan created: {lender} -> {borrower} {amount} {currency} (db_id={db_id})")
