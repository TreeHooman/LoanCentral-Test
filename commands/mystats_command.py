import logging

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$mystats"


def process_mystats_command(comment):
    """
    $mystats
    Shows the requesting user's own loan stats and health score.
    """
    from services import get_user_profile, calculate_health_score
    from config import DASHBOARD_URL

    if COMMAND_TRIGGER not in comment.body:
        return

    username = comment.author.name.lower()
    logger.info(f"$mystats requested by u/{username}")

    profile, error = get_user_profile(username)
    if error:
        comment.reply(f"Error: Could not retrieve your stats. Please try again later.")
        logger.error(f"$mystats failed for {username}: {error}")
        return

    score, label = calculate_health_score(profile)

    if profile["loans_as_borrower"] == 0 and profile["loans_as_lender"] == 0:
        comment.reply(
            f"**u/{username}**, you have no loan history in this system yet.\n\n"
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
        f"**Your loan stats, u/{username}**\n\n"
        f"|Health Score|Total Loans|Repaid|Unpaid|Active|\n"
        f"|:--:|:--:|:--:|:--:|:--:|\n"
        f"|**{score}/100** ({label})|{total}|{paid_count}|{unpaid}|{active}|\n\n"
        f"|Total Borrowed|Total Repaid|Repayment Rate|Outstanding|\n"
        f"|:--:|:--:|:--:|:--:|\n"
        f"|${borrowed:.2f}|${repaid:.2f}|{repay_pct}%|${active_amt:.2f}|"
    )

    if unpaid > 0:
        reply += f"\n\n⚠️ You have {unpaid} unpaid loan(s) on record."

    reply += f"\n\n[View full profile on LoanCentral Dashboard]({DASHBOARD_URL})"

    comment.reply(reply)
