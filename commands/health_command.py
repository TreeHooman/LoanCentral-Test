import re
import logging
from decimal import Decimal

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$health"


def _progress_bar(ratio, length=20):
    if isinstance(ratio, Decimal):
        ratio = float(ratio)
    filled = int(ratio * length)
    return "█" * filled + "░" * (length - filled)


def _health_label(score):
    if score >= 90:
        return "Excellent", "This user has an exceptional repayment history."
    elif score >= 75:
        return "Good", "This user generally repays their loans."
    elif score >= 50:
        return "Fair", "This user has a mixed repayment history."
    elif score >= 25:
        return "Poor", "This user has missed several repayments."
    else:
        return "Very Poor", "This user rarely completes loan repayments."


def process_health_command(comment):
    """Process $health command - shows a user's repayment health score."""
    from services import get_user_profile

    m = re.search(r"\$health\s+(?:/u/|u/)([^\s]+)", comment.body, re.IGNORECASE)
    if not m:
        return

    username = m.group(1).lower()
    profile, error = get_user_profile(username)

    if error:
        comment.reply(f"Error generating health report for u/{username}.")
        return

    total_loans = profile["loans_as_borrower"]
    total_borrowed = profile["amount_borrowed"]
    total_repaid = profile["amount_repaid"]
    unpaid_loans = profile["unpaid_loans"]

    if total_loans == 0:
        comment.reply(f"# Health Report for u/{username}\n\nThis user has no loan history as a borrower.")
        logger.info(f"Health report: {username} has no history")
        return

    paid_loans = total_loans - unpaid_loans
    loan_ratio = Decimal(paid_loans) / Decimal(total_loans)
    payment_ratio = Decimal(total_repaid) / Decimal(total_borrowed) if total_borrowed > 0 else Decimal("0")
    health_score = int((loan_ratio * Decimal("0.7") + payment_ratio * Decimal("0.3")) * 100)
    status, description = _health_label(health_score)

    response = (
        f"# Health Report for u/{username}\n\n"
        f"## Overall Health: {status} ({health_score}/100)\n"
        f"{description}\n\n"
        f"## Loan Completion\n"
        f"{_progress_bar(loan_ratio)} {paid_loans}/{total_loans} loans completed ({int(loan_ratio*100)}%)\n\n"
        f"## Payment Completion\n"
        f"{_progress_bar(payment_ratio)} ${total_repaid:.2f}/${total_borrowed:.2f} repaid ({int(payment_ratio*100)}%)\n\n"
        f"## Summary\n"
        f"User has borrowed ${total_borrowed:.2f} across {total_loans} loans.\n"
        f"User has repaid ${total_repaid:.2f} ({int(payment_ratio*100)}% of borrowed amount).\n"
        f"User has {unpaid_loans} unpaid loans remaining.\n\n"
        f"*This health report is generated automatically based on loan history and may not reflect all circumstances.*"
    )

    comment.reply(response)
    logger.info(f"Health report for {username}: {health_score}/100 ({status})")
