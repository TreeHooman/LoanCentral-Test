import logging
import re

from bot_messages import DASHBOARD_URL, with_dashboard_link
from commands.lender_gate import require_verified_lender

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$fund"


#: Currencies `$fund` accepts as an override. A whitelist, not "any three
#: letters": in "$fund REQ-0042 now" the word "now" is not a currency.
CURRENCIES = {
    "USD", "CAD", "EUR", "GBP", "AUD", "NZD", "CHF", "MXN", "JPY", "INR",
    "SEK", "NOK", "DKK", "PLN", "ZAR", "SGD", "HKD", "PHP", "BRL",
}

_FUND_RE = re.compile(r"\$fund\s+(REQ-[A-Z0-9]{4,16})\b([^\n]*)", re.IGNORECASE)
_AMOUNT_RE = re.compile(r"^\s*\$?(\d+(?:\.\d{1,2})?)(?![\d-])\s*([A-Za-z]{3})?\b")
_CURRENCY_RE = re.compile(r"^\s*([A-Za-z]{3})\b")


def _parse_fund(text):
    """
    Parse `$fund`. Loans recorded on Reddit keep just the amount — no repay
    amount, no due date.

      $fund REQ-0042            the request's own amount and currency
      $fund REQ-0042 CAD        the request's amount, recorded in CAD
      $fund REQ-0042 300        300, in the request's currency
      $fund REQ-0042 300USD     300 USD (a space or "$300" work too)

    Anything after that (an old-style due date, a thank-you) is ignored.
    Returns (request_id, amount or None, currency or None) or None.
    """
    match = _FUND_RE.search(text or "")
    if not match:
        return None
    request_id, rest = match.group(1).upper(), match.group(2)

    amount, currency = None, None
    amount_match = _AMOUNT_RE.match(rest)
    if amount_match:
        amount = amount_match.group(1)
        code = (amount_match.group(2) or "").upper()
        currency = code if code in CURRENCIES else None
    else:
        currency_match = _CURRENCY_RE.match(rest)
        if currency_match and currency_match.group(1).upper() in CURRENCIES:
            currency = currency_match.group(1).upper()
    return request_id, amount, currency


def process_fund_command(comment):
    """Fund an existing REQ code from Reddit and return the paid ID."""
    from services import fund_loan_request, get_request_summary, update_last_login

    parsed = _parse_fund(comment.body)
    if not parsed:
        return

    request_id, amount, currency = parsed
    lender = comment.author.name.lower()

    if not require_verified_lender(comment):
        return

    req, req_error = get_request_summary(request_id)
    if req_error:
        comment.reply(with_dashboard_link(f"Error: {req_error}"))
        return

    update_last_login(lender)
    update_last_login(req["borrower"])

    paid_id, error = fund_loan_request(request_id, lender, amount=amount, currency=currency)
    if error:
        comment.reply(with_dashboard_link(f"Error: {error}"))
        return

    loan_amount = float(amount) if amount is not None else float(req["amount"])
    loan_currency = currency or str(req["currency"] or "USD").upper()
    changed = ""
    if (amount is not None and loan_amount != float(req["amount"])) or \
            loan_currency != str(req["currency"] or "USD").upper():
        changed = f" (the request asked for {float(req['amount']):.2f} {req['currency']})"

    reply = (
        f"Loan funded from `{request_id}`.\n\n"
        f"**Paid ID:** `{paid_id}`\n\n"
        f"|Paid ID|Lender|Borrower|Amount|\n"
        f"|:--:|:--:|:--:|:--:|\n"
        f"|`{paid_id}`|u/{lender}|u/{req['borrower']}|{loan_amount:.2f} {loan_currency}{changed}|\n\n"
        f"Use this Paid ID for Reddit commands:\n"
        f"- `$paid_with_id {paid_id} [amount] {loan_currency}`\n"
        f"- `$unpaid {paid_id}`\n"
        f"- `$refunded {paid_id}`"
    )
    comment.reply(with_dashboard_link(reply))
    logger.info(f"Request {request_id} funded by {lender}; paid_id={paid_id} "
                f"{loan_amount:.2f} {loan_currency}")
