import re
import logging

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$unpaid"


def process_unpaid_command(comment):
    """
    $unpaid [loan_id]
    Lender marks a loan as unpaid. Borrower is looked up from the loan record.
    """
    from services import mark_unpaid

    match = re.search(r'\$unpaid\s+(\w+)', comment.body, re.IGNORECASE)
    if not match:
        return

    loan_id = match.group(1)
    lender = comment.author.name.lower()

    result, error = mark_unpaid(loan_id, lender)

    if error:
        comment.reply(f"Error: {error}")
        return

    borrower = result["borrower"]
    current_subreddit = comment.subreddit.display_name

    from config import DASHBOARD_URL

    response = (
        f"u/{lender} has marked their loan to u/{borrower} as unpaid.\n\n"
        f"|Lender|Borrower|Amount|Amount Repaid|\n"
        f"|:--:|:--:|:--:|:--:|\n"
        f"|u/{lender}|u/{borrower}|{result['loan_amount']:.2f} {result['currency']}"
        f"|{result['amount_repaid']:.2f} {result['currency']}|\n\n"
        f"[Submit unpaid post](https://www.reddit.com/r/{current_subreddit}/submit?selftext=true"
        f"&title=UNPAID:%20/u/{borrower}%20{result['loan_amount']}%20{result['currency']})\n\n"
        f"**[View loan details on LoanCentral Dashboard]({DASHBOARD_URL})**\n\n"
        f"If this is in error, please contact the moderators."
    )

    comment.reply(response)

    # DM the borrower so they know immediately
    try:
        from utils import reddit
        reddit.redditor(borrower).message(
            subject=f"Your loan from u/{lender} has been marked unpaid",
            message=(
                f"Hi u/{borrower},\n\n"
                f"u/{lender} has marked their loan to you as **unpaid**.\n\n"
                f"|Amount|Repaid|Remaining|\n"
                f"|:--:|:--:|:--:|\n"
                f"|{result['loan_amount']:.2f} {result['currency']}"
                f"|{result['amount_repaid']:.2f} {result['currency']}"
                f"|{result['loan_amount'] - result['amount_repaid']:.2f} {result['currency']}|\n\n"
                f"If this is incorrect, please contact the moderators or reply to the original thread.\n\n"
                f"[View your loans on LoanCentral Dashboard]({DASHBOARD_URL})"
            ),
        )
        logger.info(f"DM sent to u/{borrower} for unpaid loan {loan_id}")
    except Exception as e:
        logger.error(f"Failed to DM u/{borrower} for unpaid loan {loan_id}: {e}")

    logger.info(f"Loan {loan_id} marked unpaid by {lender}")
