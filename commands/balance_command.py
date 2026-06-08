import logging
import re

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$balance"
DASHBOARD_URL = "https://loancentral.app"


def process_balance_command(comment):
    """
    $balance [loan_id] — check remaining balance on a specific loan.
    Either the lender or borrower can use this.
    """
    from services import get_loan_history, update_last_login

    match = re.search(r'\$balance\s+([\w-]+)', comment.body, re.IGNORECASE)
    if not match:
        return

    username = comment.author.name.lower()
    loan_id = match.group(1).strip()
    update_last_login(username)

    # Search user's history (as both lender and borrower)
    loans, _ = get_loan_history(username, role="both", limit=200)
    loan = None
    if loans:
        for l in loans:
            if str(l.get("loan_id")) == loan_id or str(l.get("db_id")) == loan_id:
                loan = l
                break

    if not loan:
        comment.reply(
            f"Loan `{loan_id}` not found in your history.\n\n"
            f"*[Dashboard]({DASHBOARD_URL})*"
        )
        return

    amount = float(loan.get("amount") or 0)
    repaid = float(loan.get("amount_repaid") or 0)
    remaining = amount - repaid
    currency = loan.get("currency", "USD")
    status = loan.get("status", "unknown")
    lender = loan.get("lender")
    borrower = loan.get("borrower")

    if remaining <= 0 or status in ("repaid", "refunded"):
        msg = f"Loan `{loan_id}` is **fully settled** — no balance remaining."
    else:
        msg = (
            f"## Balance Check — Loan `{loan_id}`\n\n"
            f"|Detail|Value|\n"
            f"|:--|:--|\n"
            f"|Lender|u/{lender}|\n"
            f"|Borrower|u/{borrower}|\n"
            f"|Original Amount|{amount:.2f} {currency}|\n"
            f"|Amount Repaid|{repaid:.2f} {currency}|\n"
            f"|**Remaining Balance**|**{remaining:.2f} {currency}**|\n"
            f"|Status|{status.replace('_', ' ').title()}|\n\n"
        )
        if status == "unpaid":
            msg += "⚠️ This loan is marked **unpaid**.\n\n"

    msg += f"*[Dashboard]({DASHBOARD_URL})*"
    comment.reply(msg)
    logger.info(f"$balance: u/{username} checked loan {loan_id}")
