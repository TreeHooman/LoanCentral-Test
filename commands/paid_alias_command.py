import re
import logging
from decimal import Decimal

logger = logging.getLogger("LoanCentral")

# Use "$paid " (with trailing space) so this doesn't fire on "$paid_with_id"
COMMAND_TRIGGER = "$paid "


def process_paid_alias_command(comment):
    """
    $paid [loan_id] [amount] [currency]
    Alias for $paid_with_id — lender records a repayment.
    """
    from services import mark_repaid
    from config import DASHBOARD_URL

    match = re.search(
        r'\$paid\s+(\d+)\s+(\d+(?:\.\d+)?)\s+([A-Z]{3})',
        comment.body,
        re.IGNORECASE,
    )
    if not match:
        return

    loan_id    = match.group(1)
    amount_paid = Decimal(match.group(2))
    currency   = match.group(3).upper()
    lender     = comment.author.name.lower()

    result, error = mark_repaid(loan_id, amount_paid, currency, lender, actor_role="lender")
    if error:
        comment.reply(f"Error: {error}")
        return

    remaining = result["remaining"]
    comment.reply(
        f"u/{result['borrower']} has now repaid u/{result['lender']} {amount_paid:.2f} {result['currency']}.\n\n"
        f"|Lender|Borrower|Amount Given|Amount Repaid|Remaining|\n"
        f"|:--:|:--:|:--:|:--:|:--:|\n"
        f"|{result['lender']}|{result['borrower']}|{result['loan_amount']:.2f} {result['currency']}"
        f"|{result['new_repaid']:.2f} {result['currency']}|{remaining:.2f} {result['currency']}|\n\n"
        f"**[View full loan history on LoanCentral Dashboard]({DASHBOARD_URL})**"
    )

    # DM borrower
    try:
        from utils import reddit
        status_msg = "Your loan is now **fully repaid**. 🎉" if result['new_status'] == 'repaid' else \
                     f"Remaining balance: **{remaining:.2f} {result['currency']}**."
        reddit.redditor(result['borrower']).message(
            subject=f"Payment acknowledged — loan {loan_id}",
            message=(
                f"Hi u/{result['borrower']},\n\n"
                f"u/{result['lender']} has recorded your payment of "
                f"**{amount_paid:.2f} {result['currency']}** on loan `{loan_id}`.\n\n"
                f"{status_msg}\n\n"
                f"[View your loan history]({DASHBOARD_URL})"
            )
        )
    except Exception as e:
        logger.error(f"Failed to DM borrower for $paid alias on {loan_id}: {e}")

    try:
        from notifications import notify_discord
        note = " ✅ FULLY REPAID" if result['new_status'] == 'repaid' else ""
        notify_discord(
            f"💳 Payment: u/{result['borrower']} paid {amount_paid:.2f} {result['currency']} "
            f"to u/{result['lender']}{note} | Loan {loan_id}"
        )
    except Exception as e:
        logger.error(f"Discord notify failed for $paid alias on {loan_id}: {e}")

    logger.info(f"$paid alias: payment on loan {loan_id} by lender {lender}")
