import logging
import re

from bot_messages import DASHBOARD_URL, with_dashboard_link
from commands.lender_gate import require_verified_lender

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$fund"


def _parse_fund(text):
    """
    Parse:
      $fund REQ-0001 200 USD 2026-06-30
      $fund REQ-0001 200 2026-06-30
    Returns (request_id, repay_amount, currency, repay_date) or None.
    """
    match = re.search(
        r"\$fund\s+(REQ-\d{4,})\s+(\d+(?:\.\d+)?)(?:\s+([A-Z]{3}))?\s+(\d{4}-\d{2}-\d{2})",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return (
        match.group(1).upper(),
        match.group(2),
        (match.group(3) or "").upper(),
        match.group(4),
    )


def process_fund_command(comment):
    """Fund an existing REQ code from Reddit and return the paid ID."""
    from services import fund_loan_request, get_loan_request, update_last_login

    parsed = _parse_fund(comment.body)
    if not parsed:
        return

    request_id, repay_amount, currency, repay_date = parsed
    lender = comment.author.name.lower()

    if not require_verified_lender(comment):
        return

    req, req_error = get_loan_request(request_id)
    if req_error:
        comment.reply(with_dashboard_link(f"Error: {req_error}"))
        return
    if currency and req.get("currency") and currency != str(req["currency"]).upper():
        comment.reply(with_dashboard_link(
            f"Error: Currency mismatch. {request_id} is recorded as {req['currency']}, not {currency}."
        ))
        return

    update_last_login(lender)
    update_last_login(req["borrower"])

    paid_id, error = fund_loan_request(request_id, lender, float(repay_amount), repay_date)
    if error:
        comment.reply(with_dashboard_link(f"Error: {error}"))
        return

    reply = (
        f"Loan funded from `{request_id}`.\n\n"
        f"**Paid ID:** `{paid_id}`\n\n"
        f"|Paid ID|Lender|Borrower|Amount|Repay Amount|Due Date|\n"
        f"|:--:|:--:|:--:|:--:|:--:|:--:|\n"
        f"|`{paid_id}`|u/{lender}|u/{req['borrower']}|{float(req['amount']):.2f} {req['currency']}|"
        f"{float(repay_amount):.2f} {req['currency']}|{repay_date}|\n\n"
        f"Use this Paid ID for Reddit commands:\n"
        f"- `$paid_with_id {paid_id} [amount] {req['currency']}`\n"
        f"- `$unpaid {paid_id}`\n"
        f"- `$refunded {paid_id}`"
    )
    comment.reply(with_dashboard_link(reply))
    logger.info(f"Request {request_id} funded by {lender}; paid_id={paid_id}")
