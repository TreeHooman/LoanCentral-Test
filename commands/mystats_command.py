import logging

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$mystats"
DASHBOARD_URL = "https://loancentral.app"


def process_mystats_command(comment):
    """
    $mystats — show your own combined borrower + lender stats.
    """
    from services import get_user_profile, get_lender_stats, update_last_login

    username = comment.author.name.lower()
    update_last_login(username)

    profile, perr = get_user_profile(username)
    lender_stats, lerr = get_lender_stats(username)

    sections = [f"## Your LoanCentral Stats — u/{username}\n"]

    # --- Borrower section ---
    if profile and not perr:
        total = profile.get("loans_as_borrower", 0) or 0
        unpaid = profile.get("unpaid_loans", 0) or 0
        borrowed = float(profile.get("amount_borrowed") or 0)
        repaid_amt = float(profile.get("amount_repaid") or 0)
        outstanding = float(profile.get("active_amount") or 0)

        if total == 0:
            health = 100
        else:
            loan_ratio = (total - unpaid) / total
            pay_ratio = min(repaid_amt / borrowed, 1) if borrowed > 0 else 1
            health = round((loan_ratio * 0.7 + pay_ratio * 0.3) * 100)

        if health >= 90:   health_str = f"🟢 {health}/100 (Excellent)"
        elif health >= 70: health_str = f"🟡 {health}/100 (Good)"
        elif health >= 50: health_str = f"🟠 {health}/100 (Fair)"
        elif health >= 25: health_str = f"🔴 {health}/100 (Poor)"
        else:              health_str = f"🔴 {health}/100 (Very Poor)"

        sections.append(
            f"### As Borrower\n\n"
            f"|Stat|Value|\n"
            f"|:--|:--|\n"
            f"|Loans|{total}|\n"
            f"|Unpaid|{unpaid}|\n"
            f"|Borrowed|${borrowed:,.2f}|\n"
            f"|Repaid|${repaid_amt:,.2f}|\n"
            f"|Outstanding|${outstanding:,.2f}|\n"
            f"|Health Score|{health_str}|\n"
        )
    else:
        sections.append("### As Borrower\n\nNo borrower history found.\n")

    # --- Lender section ---
    if lender_stats and not lerr and (lender_stats.get("total_loans") or 0) > 0:
        ls = lender_stats
        total_l = ls.get("total_loans", 0) or 0
        active_l = ls.get("active_loans", 0) or 0
        unpaid_l = ls.get("unpaid_loans", 0) or 0
        repaid_l = ls.get("repaid_loans", 0) or 0
        lent = float(ls.get("total_lent") or 0)
        recovered = float(ls.get("total_recovered") or 0)
        outstanding_l = float(ls.get("outstanding") or 0)

        settled = repaid_l + unpaid_l
        if settled == 0:
            port_score = 85
        else:
            repay_ratio = repaid_l / settled
            rec_ratio = min(recovered / lent, 1) if lent > 0 else 1
            port_score = round((repay_ratio * 0.65 + rec_ratio * 0.35) * 100)

        if port_score >= 90:   ps_str = f"🟢 {port_score}/100 (Excellent)"
        elif port_score >= 70: ps_str = f"🟡 {port_score}/100 (Good)"
        elif port_score >= 50: ps_str = f"🟠 {port_score}/100 (Fair)"
        else:                  ps_str = f"🔴 {port_score}/100 (Poor)"

        sections.append(
            f"\n### As Lender\n\n"
            f"|Stat|Value|\n"
            f"|:--|:--|\n"
            f"|Total Loans|{total_l}|\n"
            f"|Active|{active_l}|\n"
            f"|Repaid|{repaid_l}|\n"
            f"|Unpaid|{unpaid_l}|\n"
            f"|Total Lent|${lent:,.2f}|\n"
            f"|Recovered|${recovered:,.2f}|\n"
            f"|Outstanding|${outstanding_l:,.2f}|\n"
            f"|Portfolio Score|{ps_str}|\n"
        )

    sections.append(f"\n*Full dashboard: [{DASHBOARD_URL}]({DASHBOARD_URL}) — sign in with Reddit.*")

    comment.reply("\n".join(sections))
    logger.info(f"$mystats: u/{username}")
