import re
import logging
from decimal import Decimal

from bot_messages import DASHBOARD_URL, with_dashboard_link

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$paid_with_id"


def _parse_paid(text):
    """Parse $paid_with_id from text. Returns (loan_id, amount, currency) or None."""
    pattern = r'\$paid_with_id\s+(\d+)\s+(\d+(?:\.\d+)?)\s+([A-Z]{3})'
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return match.group(1), Decimal(match.group(2)), match.group(3).upper()
    for block in re.findall(r'```\s*(.*?)\s*```', text, re.DOTALL):
        match = re.search(pattern, block, re.IGNORECASE)
        if match:
            return match.group(1), Decimal(match.group(2)), match.group(3).upper()
    return None


def process_paid_command(comment):
    """Process $paid_with_id command - lender records a repayment."""
    from services import mark_repaid, update_last_login

    parsed = _parse_paid(comment.body)
    if not parsed:
        return

    loan_id, amount_paid, currency = parsed
    lender = comment.author.name.lower()
    update_last_login(lender)

    result, error = mark_repaid(loan_id, amount_paid, currency, lender, actor_role="lender")

    if error:
        comment.reply(with_dashboard_link(f"Error: {error}"))
        return

    remaining = result["remaining"]
    response = (
        f"u/{result['borrower']} has now repaid u/{result['lender']} {amount_paid:.2f} {result['currency']}.\n\n"
        f"|Lender|Borrower|Amount Given|Amount Repaid|Remaining|\n"
        f"|:--:|:--:|:--:|:--:|:--:|\n"
        f"|{result['lender']}|{result['borrower']}|{result['loan_amount']:.2f} {result['currency']}"
        f"|{result['new_repaid']:.2f} {result['currency']}|{remaining:.2f} {result['currency']}|\n\n"
        f"amount specified: {amount_paid:.2f} {result['currency']}, remaining: {remaining:.2f} {result['currency']}"
    )

    response += f"\n\n---\n*View full history at [{DASHBOARD_URL}]({DASHBOARD_URL})*"
    comment.reply(with_dashboard_link(response))
    logger.info(f"Payment recorded on loan {loan_id} by lender {lender}")
