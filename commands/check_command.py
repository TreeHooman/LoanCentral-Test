import re
import logging

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$check"


def process_check_command(comment):
    """
    $check u/username
    Shows a borrower's public loan stats and health score.
    Useful for lenders doing due diligence before lending.
    """
    from services import get_user_profile, calculate_health_score, credit_tier
    from config import DASHBOARD_URL

    match = re.search(r'\$check\s+u?/?([\w-]+)', comment.body, re.IGNORECASE)
    if not match:
        return

    target = match.group(1).lower()
    requester = comment.author.name.lower()

    profile, error = get_user_profile(target)
    if error:
        comment.reply(f"Error: Could not retrieve stats for u/{target}. Please try again later.")
        logger.error(f"$check failed for {target}: {error}")
        return

    score, label = calculate_health_score(profile)
    tier = credit_tier(score)

    if profile["loans_as_borrower"] == 0 and profile["loans_as_lender"] == 0:
        comment.reply(
            f"**u/{target}** has no loan history in this system.\n\n"
            f"[View on LoanCentral Dashboard]({DASHBOARD_URL})"
        )
        return

    total = profile["loans_as_borrower"]
    unpaid = profile["unpaid_loans"]
    paid_count = total - unpaid
    borrowed = float(profile["amount_borrowed"])
    repaid = float(profile["amount_repaid"])
    active = profile["active_loans"]
    active_amt = float(profile["active_amount"])

    repay_pct = round((repaid / borrowed * 100), 1) if borrowed > 0 else 100.0

    reply = (
        f"**Loan history for u/{target}** — *{tier['label']}*\n\n"
        f"**As Borrower**\n\n"
        f"|Health Score|Credit Tier|Total Loans|Repaid|Unpaid|Active|\n"
        f"|:--:|:--:|:--:|:--:|:--:|:--:|\n"
        f"|**{score}/100** ({label})|{tier['label']}|{total}|{paid_count}|{unpaid}|{active}|\n\n"
        f"|Total Borrowed|Total Repaid|Repayment Rate|Outstanding|\n"
        f"|:--:|:--:|:--:|:--:|\n"
        f"|${borrowed:.2f}|${repaid:.2f}|{repay_pct}%|${active_amt:.2f}|"
    )

    lent_total = profile["loans_as_lender"]
    if lent_total > 0:
        lent_amt     = float(profile["amount_lent"])
        active_given = profile["active_loans_given"]
        active_given_amt = float(profile["active_amount_given"])
        bad_borrowers = profile["borrowers_unpaid"]
        reply += (
            f"\n\n**As Lender**\n\n"
            f"|Loans Given|Total Lent|Active Out|Borrowers Unpaid|\n"
            f"|:--:|:--:|:--:|:--:|\n"
            f"|{lent_total}|${lent_amt:.2f}|{active_given} (${active_given_amt:.2f})|{bad_borrowers}|"
        )

    reply += f"\n\n[View full profile on LoanCentral Dashboard]({DASHBOARD_URL})"
    comment.reply(reply)
    logger.info(f"$check on u/{target} requested by u/{requester}")
