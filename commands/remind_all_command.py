import logging

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$remindall"
DASHBOARD_URL = "https://loancentral.app"


def process_remind_all_command(comment):
    """
    $remindall — lender sends payment reminders to ALL active borrowers at once.
    Sends a single summary comment tagging all active borrowers.
    """
    from services import get_loan_history, update_last_login

    lender = comment.author.name.lower()
    update_last_login(lender)

    loans, error = get_loan_history(lender, role="lender", limit=100)
    if error or not loans:
        comment.reply("No loans found in your history.")
        return

    active = [
        l for l in loans
        if l.get("status") in ("confirmed", "partially_repaid", "unpaid")
    ]

    if not active:
        comment.reply("You have no active or unpaid loans requiring follow-up.")
        return

    # Group by borrower — keep largest remaining balance per borrower
    by_borrower = {}
    for l in active:
        b = l.get("borrower")
        if b not in by_borrower:
            by_borrower[b] = l
        else:
            existing = by_borrower[b]
            if (float(l.get("amount", 0)) - float(l.get("amount_repaid", 0))) > \
               (float(existing.get("amount", 0)) - float(existing.get("amount_repaid", 0))):
                by_borrower[b] = l

    if len(by_borrower) > 8:
        comment.reply(
            f"You have {len(by_borrower)} active borrowers — too many to batch remind. "
            f"Use `$remind u/[borrower]` for individual reminders.\n\n"
            f"*[Dashboard]({DASHBOARD_URL})*"
        )
        return

    rows = []
    for borrower, l in by_borrower.items():
        lid = l.get("loan_id") or l.get("db_id")
        amt = float(l.get("amount", 0))
        rep = float(l.get("amount_repaid", 0))
        remaining = amt - rep
        rows.append(f"|u/{borrower}|`{lid}`|{remaining:.2f} {l.get('currency','USD')}|")

    header = "|Borrower|Loan ID|Remaining|\n|:--|:--:|--:|\n"
    table = header + "\n".join(rows)

    comment.reply(
        f"Payment reminder — u/{lender} has {len(by_borrower)} outstanding loan(s):\n\n"
        f"{table}\n\n"
        f"Please reach out or arrange repayment at your earliest convenience.\n\n"
        f"*[Dashboard]({DASHBOARD_URL})*"
    )
    logger.info(f"$remindall: u/{lender} sent bulk reminder to {len(by_borrower)} borrowers")
