import logging
import re

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$remind"
DASHBOARD_URL = "https://loancentral.app"


def process_remind_command(comment):
    """
    $remind u/borrower [loan_id]
    Lender sends a payment reminder to a borrower.
    Loan ID is optional — if omitted, the most recent active loan is used.
    """
    from services import get_loan_history, update_last_login

    lender = comment.author.name.lower()
    update_last_login(lender)

    # Parse: $remind u/borrower [optional_loan_id]
    match = re.search(
        r'\$remind\s+u?/?(\w+)(?:\s+(\S+))?',
        comment.body, re.IGNORECASE,
    )
    if not match:
        return

    borrower = match.group(1).lower()
    loan_id = match.group(2)

    if lender == borrower:
        comment.reply("You cannot remind yourself.")
        return

    loan = None

    if loan_id:
        # Search lender's history for this loan ID
        loans, _ = get_loan_history(lender, role="lender", limit=200)
        if loans:
            for l in loans:
                if str(l.get("loan_id")) == loan_id or str(l.get("db_id")) == loan_id:
                    loan = l
                    break
        if not loan:
            comment.reply(f"Loan `{loan_id}` not found in your loan history.")
            return
    else:
        # Find the most recent active loan between lender and borrower
        loans, _ = get_loan_history(lender, role="lender", limit=50)
        if loans:
            active = [
                l for l in loans
                if l.get("borrower") == borrower
                and l.get("status") in ("confirmed", "partially_repaid", "unpaid")
            ]
            if active:
                loan = sorted(active, key=lambda l: l.get("date_created") or "", reverse=True)[0]

    if not loan:
        comment.reply(
            f"No active loan found between you and u/{borrower}. "
            f"Check your dashboard: {DASHBOARD_URL}"
        )
        return

    loan_id = loan.get("loan_id") or loan.get("db_id")
    amount = float(loan.get("amount") or 0)
    repaid = float(loan.get("amount_repaid") or 0)
    remaining = amount - repaid
    currency = loan.get("currency", "USD")

    comment.reply(
        f"u/{borrower} — payment reminder from u/{lender}\n\n"
        f"**Loan `{loan_id}`** — you still owe **{remaining:.2f} {currency}** "
        f"({repaid:.2f} repaid of {amount:.2f} total)\n\n"
        f"u/{lender} will record repayment using:\n\n"
        f"    $paid {loan_id} {remaining:.2f} {currency}\n\n"
        f"*[Dashboard]({DASHBOARD_URL})*"
    )
    logger.info(f"$remind: u/{lender} reminded u/{borrower} about loan {loan_id}")
