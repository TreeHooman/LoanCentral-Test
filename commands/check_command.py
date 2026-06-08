import logging

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$check"
DASHBOARD_URL = "https://loancentral.app"


def process_check_command(comment):
    """
    $check u/username — look up a borrower's public loan stats.
    Useful for lenders vetting potential borrowers.
    """
    from services import get_user_profile, update_last_login
    import re

    match = re.search(r'\$check\s+u?/?(\w+)', comment.body, re.IGNORECASE)
    if not match:
        return

    requester = comment.author.name.lower()
    target = match.group(1).lower()

    update_last_login(requester)

    profile, error = get_user_profile(target)
    if error or not profile:
        comment.reply(
            f"u/{target} has no loan history in our system.\n\n"
            f"*LoanCentral — [Dashboard]({DASHBOARD_URL})*"
        )
        return

    total = profile.get("loans_as_borrower", 0) or 0
    unpaid = profile.get("unpaid_loans", 0) or 0
    repaid_count = total - unpaid  # approximate
    borrowed = float(profile.get("amount_borrowed") or 0)
    repaid_amt = float(profile.get("amount_repaid") or 0)
    outstanding = float(profile.get("active_amount") or 0)

    if total == 0:
        health = 100
    else:
        loan_ratio = (total - unpaid) / total
        pay_ratio = min(repaid_amt / borrowed, 1) if borrowed > 0 else 1
        health = round((loan_ratio * 0.7 + pay_ratio * 0.3) * 100)

    if health >= 90:
        health_label = "Excellent"
        health_sym = "🟢"
    elif health >= 70:
        health_label = "Good"
        health_sym = "🟡"
    elif health >= 50:
        health_label = "Fair"
        health_sym = "🟠"
    elif health >= 25:
        health_label = "Poor"
        health_sym = "🔴"
    else:
        health_label = "Very Poor"
        health_sym = "🔴"

    reply = (
        f"## Borrower Profile: u/{target}\n\n"
        f"|Stat|Value|\n"
        f"|:--|:--|\n"
        f"|Total Loans|{total}|\n"
        f"|Unpaid|{unpaid}|\n"
        f"|Total Borrowed|${borrowed:,.2f}|\n"
        f"|Total Repaid|${repaid_amt:,.2f}|\n"
        f"|Outstanding|${outstanding:,.2f}|\n"
        f"|Health Score|{health_sym} **{health}/100** ({health_label})|\n\n"
    )

    if unpaid > 0:
        reply += f"⚠️ This user has **{unpaid} unpaid loan(s)**.\n\n"

    reply += f"*Full profile: [{DASHBOARD_URL}/u/{target}]({DASHBOARD_URL}/u/{target})*"

    comment.reply(reply)
    logger.info(f"$check: u/{requester} checked u/{target}")
