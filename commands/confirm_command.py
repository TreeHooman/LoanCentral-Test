"""$confirm — the borrower confirms a `$loan` offer, which records the loan.

    $confirm                          the offer in this thread, or their only one
    $confirm u/lender                 the offer from that lender
    $confirm /u/lender 100.00 USD     the original bot's form, still accepted

Only the borrower the offer was made to can confirm it (offers.confirm_offer).
"""

import logging
import re
from decimal import Decimal

from bot_messages import with_dashboard_link

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$confirm"

_CONFIRM_RE = re.compile(
    r"\$confirm\b(?:\s+/?u/([\w-]+))?(?:\s+\$?(\d+(?:\.\d{1,2})?)\s*([A-Za-z]{3})\b)?",
    re.IGNORECASE)


def process_confirm_command(comment):
    from offers import confirm_offer, pick_offer

    match = _CONFIRM_RE.search(comment.body or "")
    if not match:
        return
    borrower = comment.author.name.lower()
    lender = match.group(1)
    amount = Decimal(match.group(2)) if match.group(2) else None
    currency = match.group(3).upper() if match.group(3) else None

    permalink = getattr(getattr(comment, "submission", None), "permalink", "") or ""
    thread_url = f"https://www.reddit.com{permalink}" if permalink else None
    offer, error = pick_offer(borrower, lender=lender, amount=amount, currency=currency,
                              thread_url=thread_url)
    if error:
        comment.reply(with_dashboard_link(f"Error: {error}"))
        return

    db_id, offer, error = confirm_offer(offer["id"], borrower)
    if error:
        comment.reply(with_dashboard_link(f"Error: {error}"))
        return

    lender, amount, currency = offer["lender"], offer["amount"], offer["currency"]
    comment.reply(with_dashboard_link(
        f"Confirmed: u/{borrower} has received **{amount:.2f} {currency}** from u/{lender}.\n\n"
        f"|Paid ID|Lender|Borrower|Amount|\n"
        f"|:--:|:--:|:--:|:--:|\n"
        f"|`{db_id}`|u/{lender}|u/{borrower}|{amount:.2f} {currency}|\n\n"
        f"**Lender commands:**\n"
        f"- Record repayment: `$paid_with_id {db_id} [amount] {currency}`\n"
        f"- Mark unpaid: `$unpaid {db_id}`\n"
        f"- Cancel loan: `$refunded {db_id}`"
    ))
    logger.info(f"Loan offer {offer['id']} confirmed by {borrower}: loan {db_id}")
