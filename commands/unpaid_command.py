import re
import logging

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$unpaid"


DASHBOARD_URL = "https://loancentral.app"


def process_unpaid_command(comment):
    """
    $unpaid [loan_id]
    Lender marks a loan as unpaid. Borrower is looked up from the loan record.
    """
    from services import mark_unpaid, update_last_login

    match = re.search(r'\$unpaid\s+(\w+)', comment.body, re.IGNORECASE)
    if not match:
        return

    loan_id = match.group(1)
    lender = comment.author.name.lower()
    update_last_login(lender)

    result, error = mark_unpaid(loan_id, lender)

    if error:
        comment.reply(f"Error: {error}")
        return

    borrower = result["borrower"]
    current_subreddit = comment.subreddit.display_name

    response = (
        f"u/{lender} has marked their loan to u/{borrower} as unpaid.\n\n"
        f"|Lender|Borrower|Amount|Amount Repaid|\n"
        f"|:--:|:--:|:--:|:--:|\n"
        f"|u/{lender}|u/{borrower}|{result['loan_amount']:.2f} {result['currency']}"
        f"|{result['amount_repaid']:.2f} {result['currency']}|\n\n"
        f"[Submit unpaid post](https://www.reddit.com/r/{current_subreddit}/submit?selftext=true"
        f"&title=UNPAID:%20/u/{borrower}%20{result['loan_amount']}%20{result['currency']})\n\n"
        f"If this is in error, u/{borrower} can comment `$dispute {loan_id}` to flag for mod review.\n\n"
        f"*Manage this at [{DASHBOARD_URL}]({DASHBOARD_URL})*"
    )

    comment.reply(response)
    logger.info(f"Loan {loan_id} marked unpaid by {lender}")
