import re
import logging

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$unpaid"


def _parse_unpaid(text):
    """Parse $unpaid from text. Returns (loan_id, borrower) or None."""
    pattern = r'\$unpaid\s+(\d+)\s+u?\/?([\w-]+)'
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return match.group(1), match.group(2).lower()
    return None


def process_unpaid_command(comment):
    """Process $unpaid command - lender marks loan as unpaid."""
    from services import mark_unpaid

    parsed = _parse_unpaid(comment.body)
    if not parsed:
        return

    loan_id, borrower = parsed
    lender = comment.author.name.lower()

    result, error = mark_unpaid(loan_id, borrower, lender)

    if error:
        comment.reply(f"Error: {error}")
        return

    current_subreddit = comment.subreddit.display_name
    response = (
        f"u/{lender} has marked their loan to u/{borrower} as unpaid.\n\n"
        f"|Lender|Borrower|Amount|Amount Repaid|Date|Original Thread|\n"
        f"|:--:|:--:|:--:|:--:|:--:|:--:|\n"
        f"|{lender}|{borrower}|{result['loan_amount']:.2f} {result['currency']}"
        f"|{result['amount_repaid']:.2f} {result['currency']}|"
        f"{__import__('datetime').datetime.now().strftime('%Y-%m-%d')}|[Link]({result['thread_url']})|\n\n"
        f"[Submit unpaid post](https://www.reddit.com/r/{current_subreddit}/submit?selftext=true"
        f"&title=UNPAID:%20/u/{borrower}%20{result['loan_amount']}%20{result['currency']})\n\n"
        f"If this is in error, please contact the moderators."
    )

    comment.reply(response)
    logger.info(f"Loan {loan_id} marked unpaid by {lender}")
