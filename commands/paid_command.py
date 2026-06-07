import re
import logging
from decimal import Decimal

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
    from services import mark_repaid

    parsed = _parse_paid(comment.body)
    if not parsed:
        return

    loan_id, amount_paid, currency = parsed
    lender = comment.author.name.lower()

    result, error = mark_repaid(loan_id, amount_paid, currency, lender, actor_role="lender")

    if error:
        comment.reply(f"Error: {error}")
        return

    from config import DASHBOARD_URL

    remaining = result["remaining"]
    response = (
        f"u/{result['borrower']} has now repaid u/{result['lender']} {amount_paid:.2f} {result['currency']}.\n\n"
        f"|Lender|Borrower|Amount Given|Amount Repaid|Remaining|\n"
        f"|:--:|:--:|:--:|:--:|:--:|\n"
        f"|{result['lender']}|{result['borrower']}|{result['loan_amount']:.2f} {result['currency']}"
        f"|{result['new_repaid']:.2f} {result['currency']}|{remaining:.2f} {result['currency']}|\n\n"
        f"amount specified: {amount_paid:.2f} {result['currency']}, remaining: {remaining:.2f} {result['currency']}\n\n"
        f"**[View full loan history on LoanCentral Dashboard]({DASHBOARD_URL})**"
    )

    comment.reply(response)

    # DM the borrower to confirm their payment has been acknowledged
    try:
        from utils import reddit
        from config import DASHBOARD_URL as _DURL
        status_msg = "Your loan is now **fully repaid**. 🎉" if result['new_status'] == 'repaid' else \
                     f"Remaining balance: **{result['remaining']:.2f} {result['currency']}**."
        reddit.redditor(result['borrower']).message(
            subject=f"Payment acknowledged — loan {loan_id}",
            message=(
                f"Hi u/{result['borrower']},\n\n"
                f"u/{result['lender']} has recorded your payment of "
                f"**{amount_paid:.2f} {result['currency']}** on loan `{loan_id}`.\n\n"
                f"{status_msg}\n\n"
                f"[View your loan history on LoanCentral Dashboard]({_DURL})"
            )
        )
        logger.info(f"DM sent to u/{result['borrower']} for payment on loan {loan_id}")
    except Exception as e:
        logger.error(f"Failed to DM u/{result['borrower']} for payment on {loan_id}: {e}")

    try:
        from notifications import notify_discord
        status_note = " ✅ FULLY REPAID" if result['new_status'] == 'repaid' else ""
        notify_discord(f"💳 Payment: u/{result['borrower']} paid {amount_paid:.2f} {result['currency']} to u/{result['lender']}{status_note} | Loan {loan_id}")
    except Exception as e:
        logger.error(f"Discord notify failed for payment on {loan_id}: {e}")

    logger.info(f"Payment recorded on loan {loan_id} by lender {lender}")
