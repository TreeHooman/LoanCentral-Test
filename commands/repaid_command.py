import re
import logging
from decimal import Decimal

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$repaid"


def _parse_repaid(text):
    """Parse $repaid from text. Returns (loan_id, amount, currency) or None."""
    pattern = r'\$repaid\s+(\d+)\s+(\d+(?:\.\d+)?)\s+([A-Z]{3})'
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return match.group(1), Decimal(match.group(2)), match.group(3).upper()
    for block in re.findall(r'```\s*(.*?)\s*```', text, re.DOTALL):
        match = re.search(pattern, block, re.IGNORECASE)
        if match:
            return match.group(1), Decimal(match.group(2)), match.group(3).upper()
    return None


def process_repaid_command(comment):
    """Process $repaid command - borrower records their own repayment."""
    from services import mark_repaid

    parsed = _parse_repaid(comment.body)
    if not parsed:
        return

    loan_id, repay_amt, currency = parsed
    borrower = comment.author.name.lower()

    result, error = mark_repaid(loan_id, repay_amt, currency, borrower, actor_role="borrower")

    if error:
        comment.reply(f"Error: {error}")
        return

    remaining = result["remaining"]
    response = (
        f"u/{result['borrower']} repaid {repay_amt:.2f} {result['currency']} to u/{result['lender']}.\n\n"
        f"|Loan ID|Lender|Borrower|Original Amount|Amount Repaid|Remaining|\n"
        f"|:--:|:--:|:--:|:--:|:--:|:--:|\n"
        f"|{result['db_id']}|{result['lender']}|{result['borrower']}"
        f"|{result['loan_amount']:.2f} {result['currency']}"
        f"|{result['new_repaid']:.2f} {result['currency']}"
        f"|{remaining:.2f} {result['currency']}|\n\n"
    )
    if remaining > 0:
        response += f"You still need to repay {remaining:.2f} {result['currency']}."
    else:
        response += "This loan has now been fully repaid! Thank you!"

    comment.reply(response)
    logger.info(f"Repayment recorded on loan {loan_id} by borrower {borrower}")
