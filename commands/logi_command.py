import logging
import re
from decimal import Decimal

from bot_messages import with_dashboard_link

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$logi"


def _money(value):
    amount = Decimal(str(value or 0))
    return f"${amount:,.2f}"


def process_logi_command(comment):
    """Process $logi u/[lender] - shows a lender's recorded stats."""
    match = re.search(r"\$logi\s+u?/?([\w-]+)", comment.body, re.IGNORECASE)
    if not match:
        return

    lender = match.group(1).lower()

    from services import get_lender_stats

    stats, error = get_lender_stats(lender)
    if error:
        comment.reply(with_dashboard_link(f"Error: {error}"))
        return

    stats = stats or {}
    comment.reply(with_dashboard_link(
        f"**Lender Snapshot: u/{lender}**\n\n"
        f"| Metric | Value |\n"
        f"|:--|--:|\n"
        f"| Amount Lent | {_money(stats.get('total_lent'))} |\n"
        f"| Received Back | {_money(stats.get('total_recovered'))} |\n"
        f"| Total Loans | {int(stats.get('total_loans') or 0)} |\n"
        f"| Ongoing Loans | {int(stats.get('active_loans') or 0)} |\n"
        f"| Paid Loans | {int(stats.get('repaid_loans') or 0)} |\n"
        f"| Unpaid Loans | {int(stats.get('unpaid_loans') or 0)} |\n\n"
        f"*LoanCentral stats are based on recorded dashboard and bot activity.*"
    ))
    logger.info(f"Lender snapshot sent for u/{lender} to u/{comment.author.name}")
