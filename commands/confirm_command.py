import re
import logging
from decimal import Decimal

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$confirm"


def _parse_confirm(text):
    """Parse $confirm from text. Returns (lender, amount, currency) or None."""
    pattern = r'\$confirm\s+\/?u\/([^\s]+)\s+(\d+(?:\.\d+)?)\s+([A-Z]{3})'
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return match.group(1).lower(), Decimal(match.group(2)), match.group(3).upper()
    # Check code blocks
    for block in re.findall(r'```\s*(.*?)\s*```', text, re.DOTALL):
        match = re.search(pattern, block, re.IGNORECASE)
        if match:
            return match.group(1).lower(), Decimal(match.group(2)), match.group(3).upper()
    return None


def process_confirm_command(comment):
    """Process $confirm command - confirms a loan and creates database entry."""
    from services import create_loan

    parsed = _parse_confirm(comment.body)
    if not parsed:
        return

    lender, amount, currency = parsed
    borrower = comment.author.name.lower()

    # Only the OP of the post can confirm
    post = comment.submission
    if borrower != post.author.name.lower():
        comment.reply(
            f"Error: Only the original requester (u/{post.author.name}) can confirm this loan."
        )
        return

    thread_url = f"https://www.reddit.com{post.permalink}"
    db_id, error = create_loan(lender, borrower, amount, currency, thread_url)

    if error:
        comment.reply(f"Error: {error}")
        return

    comment.reply(
        f"Confirmed: u/{borrower} has confirmed receiving {amount:.2f} {currency} from u/{lender}.\n\n"
        f"To mark this loan repaid later, the lender uses:\n\n"
        f"```\n$paid_with_id {db_id} {amount:.2f} {currency}\n```\n\n"
        f"If the loan did not go through, the *lender* should reply to this comment with 'Refunded'."
    )
    logger.info(f"Confirmed loan: {borrower} received {amount} {currency} from {lender} (id={db_id})")
