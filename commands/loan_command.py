import re
import logging
from decimal import Decimal
from datetime import datetime, timedelta

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$loan"


def _parse_due_date(due_str):
    """Parse '30d', '2w', '1m' into a future datetime."""
    if not due_str:
        return None
    m = re.match(r'^(\d+)([dwm])$', due_str.lower())
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    if unit == 'd':
        return datetime.now() + timedelta(days=n)
    if unit == 'w':
        return datetime.now() + timedelta(weeks=n)
    if unit == 'm':
        return datetime.now() + timedelta(days=n * 30)
    return None


def process_loan_command(comment):
    """
    $loan [amount] [currency] u/[borrower] [due:30d]
    Lender records a loan immediately — no borrower confirmation needed.
    Optional: due:Nd / due:Nw / due:Nm sets a due date.
    """
    from services import create_loan

    match = re.search(
        r'\$loan\s+(\d+(?:\.\d+)?)\s+([A-Z]{3})\s+u?/?([\w-]+)(?:\s+due:(\d+[dwm]))?',
        comment.body,
        re.IGNORECASE,
    )
    if not match:
        return

    lender = comment.author.name.lower()
    amount = Decimal(match.group(1))
    currency = match.group(2).upper()
    borrower = match.group(3).lower()
    due_date = _parse_due_date(match.group(4))

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
    db_id, error = create_loan(lender, borrower, amount, currency, thread_url, due_date=due_date)

    if error:
        comment.reply(f"Error: {error}")
        return

    from config import DASHBOARD_URL

    due_col  = "|Due Date" if due_date else ""
    due_sep  = "|:--:"    if due_date else ""
    due_val  = f"|{due_date.strftime('%Y-%m-%d')}" if due_date else ""

    comment.reply(
        f"Loan recorded!\n\n"
        f"|Loan ID|Lender|Borrower|Amount|Currency{due_col}|\n"
        f"|:--:|:--:|:--:|:--:|:--:{due_sep}|\n"
        f"|**{db_id}**|u/{lender}|u/{borrower}|{amount:.2f}|{currency}{due_val}|\n\n"
        f"u/{borrower} — you have received **{amount:.2f} {currency}** from u/{lender}. "
        f"Use loan ID `{db_id}` for all future references to this loan.\n\n"
        f"**Lender commands:**\n"
        f"- Record repayment: `$paid_with_id {db_id} [amount] {currency}`\n"
        f"- Mark unpaid: `$unpaid {db_id}`\n"
        f"- Cancel loan: `$refunded {db_id}`\n\n"
        f"**[View on LoanCentral Dashboard]({DASHBOARD_URL})** — loan history, health scores, stats."
    )

    # DM the borrower so they know a loan has been recorded against them
    try:
        from utils import reddit
        reddit.redditor(borrower).message(
            subject=f"Loan recorded: u/{lender} has lent you {amount:.2f} {currency}",
            message=(
                f"Hi u/{borrower},\n\n"
                f"u/{lender} has recorded a loan to you:\n\n"
                f"|Loan ID|Amount|Currency|\n"
                f"|:--:|:--:|:--:|\n"
                f"|`{db_id}`|{amount:.2f}|{currency}|\n\n"
                f"Use loan ID `{db_id}` for all future references to this loan.\n\n"
                f"If you did not receive this loan or this is incorrect, "
                f"please contact the moderators.\n\n"
                f"[View your loans on LoanCentral Dashboard]({DASHBOARD_URL})"
            ),
        )
        logger.info(f"DM sent to u/{borrower} for new loan {db_id}")
    except Exception as e:
        logger.error(f"Failed to DM u/{borrower} for loan {db_id}: {e}")

    try:
        from notifications import notify_discord
        due_note = f" (due {due_date.strftime('%Y-%m-%d')})" if due_date else ""
        notify_discord(f"💰 New loan: u/{lender} → u/{borrower} {amount:.2f} {currency}{due_note} | ID: {db_id}")
    except Exception as e:
        logger.error(f"Discord notify failed for loan {db_id}: {e}")

    logger.info(f"Loan created: {lender} -> {borrower} {amount} {currency} (db_id={db_id})")
