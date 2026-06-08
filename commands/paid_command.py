import re
import logging
from decimal import Decimal

from bot_messages import DASHBOARD_URL, with_dashboard_link

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$paid_with_id"


def _parse_paid(text):
    """Parse $paid_with_id from text. Returns (loan_id, amount, currency) or None."""
    pattern = r'\$paid_with_id\s+([A-Z0-9_-]+)\s+(\d+(?:\.\d+)?)\s+([A-Z]{3})'
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
    fully_repaid = remaining <= 0
    status_line = "**Loan fully repaid.**" if fully_repaid else f"**Remaining balance: {remaining:.2f} {result['currency']}**"

    response = (
        f"Payment recorded.\n\n"
        f"|Paid ID|Lender|Borrower|Lent|This Payment|Total Repaid|Remaining|\n"
        f"|:--:|:--:|:--:|:--:|:--:|:--:|:--:|\n"
        f"|{loan_id}|u/{result['lender']}|u/{result['borrower']}"
        f"|{result['loan_amount']:.2f} {result['currency']}"
        f"|{amount_paid:.2f} {result['currency']}"
        f"|{result['new_repaid']:.2f} {result['currency']}"
        f"|{remaining:.2f} {result['currency']}|\n\n"
        f"{status_line}"
    )
    if not fully_repaid:
        response += f"\n\nNext payment: `$paid_with_id {loan_id} [amount] {result['currency']}`"

    response += f"\n\n---\n*View full history at [{DASHBOARD_URL}]({DASHBOARD_URL})*"
    comment.reply(with_dashboard_link(response))
    logger.info(f"Payment recorded on loan {loan_id} by lender {lender}")
