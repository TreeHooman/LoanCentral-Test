import re
import logging
from decimal import Decimal

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$apply"


def process_apply_command(comment):
    """
    $apply [amount] [currency] [reason...]
    Submit a loan application from Reddit. Lenders can claim it on the dashboard.
    """
    from services import submit_loan_application
    from config import DASHBOARD_URL

    match = re.search(
        r'\$apply\s+(\d+(?:\.\d+)?)\s+([A-Z]{3})(?:\s+(.+))?',
        comment.body,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return

    borrower = comment.author.name.lower()
    amount   = Decimal(match.group(1))
    currency = match.group(2).upper()
    reason   = (match.group(3) or "").strip()[:500]

    if amount <= 0:
        comment.reply("Error: Loan amount must be greater than zero.")
        return

    app_id, error = submit_loan_application(borrower, amount, currency, reason)
    if error:
        comment.reply(f"Error: {error}")
        return

    comment.reply(
        f"Loan application submitted!\n\n"
        f"|Application ID|Amount|Currency|\n"
        f"|:--:|:--:|:--:|\n"
        f"|**#{app_id}**|{amount:.2f}|{currency}|\n\n"
        f"Verified lenders can see and claim your application on the "
        f"[LoanCentral Dashboard]({DASHBOARD_URL}).\n\n"
        f"You'll receive a Reddit message if a lender claims your request. "
        f"Use `$apply cancel #{app_id}` to withdraw it.\n\n"
        f"*Note: Posting a loan application does not guarantee funding. "
        f"Only lend/borrow with users you trust.*"
    )
    logger.info(f"Loan application #{app_id} submitted by u/{borrower}: {amount} {currency}")
