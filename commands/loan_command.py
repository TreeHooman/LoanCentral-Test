import re
import logging
from decimal import Decimal

from bot_messages import DASHBOARD_URL, with_dashboard_link

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$loan"


def _parse_repay_amount(text):
    """
    Try to extract an agreed repay amount from the post title/body.
    Looks for patterns like: repay 130, pay back 130, return 130, to repay 130.
    Returns Decimal or None. Never shown on Reddit — stored in DB only.
    """
    patterns = [
        r'(?:repay(?:ment)?|pay\s*back|pay\s*back|return|to\s+repay|payback)\s+\$?(\d+(?:\.\d+)?)',
        r'\$?(\d+(?:\.\d+)?)\s+(?:repay|payback|pay\s*back)',
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                return Decimal(m.group(1))
            except Exception:
                pass
    return None


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
        comment.reply(with_dashboard_link("Error: You cannot lend to yourself."))
        return

    if amount <= 0:
        comment.reply(with_dashboard_link("Error: Loan amount must be greater than zero."))
        return

    # Verify lender status — database is source of truth, not Reddit flair.
    try:
        from services import get_verified_lender_status
        is_verified, _, _err = get_verified_lender_status(lender)
        if not is_verified:
            comment.reply(with_dashboard_link(
                "Error: Your account has not completed the LoanCentral lender verification process. "
                "Contact a moderator to begin the process."
            ))
            return
    except Exception as e:
        logger.error(f"Error checking verified lender status for {lender}: {e}")
        comment.reply(with_dashboard_link(
            "Error: Unable to verify your lender status. Please contact the moderators."
        ))
        return

    from services import update_last_login
    update_last_login(lender)
    update_last_login(borrower)

    thread_url = f"https://www.reddit.com{comment.submission.permalink}"
    post_text = f"{comment.submission.title} {comment.body}"
    repay_amount = _parse_repay_amount(post_text)
    db_id, error = create_loan(lender, borrower, amount, currency, thread_url,
                               repay_amount=repay_amount)

    if error:
        comment.reply(with_dashboard_link(f"Error: {error}"))
        return

    comment.reply(with_dashboard_link(
        f"Loan recorded!\n\n"
        f"|Paid ID|Lender|Borrower|Amount|Currency|\n"
        f"|:--:|:--:|:--:|:--:|:--:|\n"
        f"|**{db_id}**|u/{lender}|u/{borrower}|{amount:.2f}|{currency}|\n\n"
        f"u/{borrower} — you have received **{amount:.2f} {currency}** from u/{lender}. "
        f"Use Paid ID `{db_id}` for all future references to this loan.\n\n"
        f"**Lender commands:**\n"
        f"- Record repayment: `$paid_with_id {db_id} [amount] {currency}`\n"
        f"- Mark unpaid: `$unpaid {db_id}`\n"
        f"- Cancel loan: `$refunded {db_id}`\n\n"
        f"---\n"
        f"*Track loans, view history & manage everything at [{DASHBOARD_URL}]({DASHBOARD_URL}) — sign in with Reddit.*"
    ))
    logger.info(f"Loan created: {lender} -> {borrower} {amount} {currency} (db_id={db_id})")
