import re
import logging
from decimal import Decimal

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$paid"
DASHBOARD_URL = "https://loancentral.app"

_PATTERN = r'\$paid(?:_with_id)?\s+([\w-]+)\s+(\d+(?:\.\d+)?)\s+([A-Z]{3})'


def _parse_paid(text):
    """Parse $paid or $paid_with_id. Returns (loan_id, amount, currency) or None."""
    match = re.search(_PATTERN, text, re.IGNORECASE)
    if match:
        return match.group(1), Decimal(match.group(2)), match.group(3).upper()
    for block in re.findall(r'```\s*(.*?)\s*```', text, re.DOTALL):
        match = re.search(_PATTERN, block, re.IGNORECASE)
        if match:
            return match.group(1), Decimal(match.group(2)), match.group(3).upper()
    return None


def process_paid_command(comment):
    """Process $paid or $paid_with_id — lender records a repayment."""
    from services import mark_repaid, update_last_login

    parsed = _parse_paid(comment.body)
    if not parsed:
        return

    loan_id, amount_paid, currency = parsed
    lender = comment.author.name.lower()
    update_last_login(lender)

    result, error = mark_repaid(loan_id, amount_paid, currency, lender, actor_role="lender")
    if error:
        comment.reply(f"Error: {error}")
        return

    remaining = result["remaining"]
    status_line = "✓ Fully repaid!" if remaining <= 0 else f"Remaining: **{remaining:.2f} {result['currency']}**"
    comment.reply(
        f"Payment recorded — u/{result['borrower']} paid u/{result['lender']} "
        f"**{amount_paid:.2f} {result['currency']}**\n\n"
        f"{status_line}\n\n"
        f"*[Dashboard]({DASHBOARD_URL})*"
    )
    logger.info(f"Payment recorded on loan {loan_id} by lender {lender}")
