"""$loan — a verified lender offers a loan; the borrower must `$confirm` it.

    $loan 100 USD                in a [REQ] thread: offer to the post's author
    $loan 100 USD u/borrower     offer to someone named

Nothing reaches anyone's record until the borrower confirms (offers.py), as
the original bot worked. `$fund` is different: it is tied to the borrower's
own [REQ] post, so it records straight away.
"""

import logging
import re
from decimal import Decimal

from bot_messages import with_dashboard_link
from commands.lender_gate import require_verified_lender

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$loan"

_LOAN_RE = re.compile(r"\$loan\s+\$?(\d+(?:\.\d{1,2})?)\s*([A-Za-z]{3})\b(?:\s+/?u/([\w-]+))?",
                      re.IGNORECASE)


def process_loan_command(comment):
    from offers import OFFER_DAYS, create_offer

    match = _LOAN_RE.search(comment.body or "")
    if not match:
        return

    lender = comment.author.name.lower()
    amount = Decimal(match.group(1))
    currency = match.group(2).upper()
    named = match.group(3)
    submission = getattr(comment, "submission", None)
    post_author = getattr(getattr(submission, "author", None), "name", None)
    borrower = (named or post_author or "").lower()
    if not borrower:
        comment.reply(with_dashboard_link(
            "Error: Say who the loan is for: `$loan 100 USD u/borrower`."))
        return

    if not require_verified_lender(comment):
        return

    permalink = getattr(submission, "permalink", "") or ""
    thread_url = f"https://www.reddit.com{permalink}" if permalink else ""
    offer, error = create_offer(lender, borrower, amount, currency, thread_url)
    if error:
        comment.reply(with_dashboard_link(f"Error: {error}"))
        return

    comment.reply(with_dashboard_link(
        f"u/{lender} is offering **{amount:.2f} {currency}** to u/{borrower}.\n\n"
        f"u/{borrower}, once you have received the money, confirm it by replying:\n\n"
        f"`$confirm`\n\n"
        f"(or `$confirm u/{lender} {amount:.2f} {currency}` if you have more than one offer).\n\n"
        f"The loan is only recorded after you confirm. "
        f"This offer expires in {OFFER_DAYS} days."
    ))
    logger.info(f"Loan offer {offer['id']}: {lender} -> {borrower} {amount} {currency}")
