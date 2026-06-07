import re
import logging
from decimal import Decimal

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$apply"


def process_apply_command(comment):
    """
    $apply [amount] [currency] [reason...]   — post loan application
    $apply cancel #[id]                      — cancel a pending application
    """
    from config import DASHBOARD_URL

    body = comment.body
    borrower = comment.author.name.lower()

    # Cancel subcommand
    cancel_match = re.search(r'\$apply\s+cancel\s+#?(\d+)', body, re.IGNORECASE)
    if cancel_match:
        from services import update_loan_application, get_loan_applications
        app_id = int(cancel_match.group(1))
        apps, _ = get_loan_applications(borrower=borrower)
        app = next((a for a in apps if a["id"] == app_id), None)
        if not app:
            comment.reply(f"No open application #{app_id} found under your account.")
            return
        if app["status"] != "open":
            comment.reply(f"Application #{app_id} is already {app['status']} and cannot be cancelled.")
            return
        ok, error = update_loan_application(app_id, "cancelled", borrower)
        if error:
            comment.reply(f"Error: {error}")
            return
        comment.reply(f"Application #{app_id} cancelled.")
        logger.info(f"Loan application #{app_id} cancelled by u/{borrower}")
        return

    from services import submit_loan_application

    match = re.search(
        r'\$apply\s+(\d+(?:\.\d+)?)\s+([A-Z]{3})(?:\s+(.+))?',
        body,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return

    borrower = comment.author.name.lower()
    amount   = Decimal(match.group(1))
    currency = match.group(2).upper()
    reason   = (match.group(3) or "").strip()[:500]

    if amount <= 0:
        comment.reply("Error: Loan amount must be greater than zero.")
        return

    app_id, error = submit_loan_application(borrower, amount, currency, reason)
    if error:
        comment.reply(f"Error: {error}")
        return

    comment.reply(
        f"Loan application submitted!\n\n"
        f"|Application ID|Amount|Currency|\n"
        f"|:--:|:--:|:--:|\n"
        f"|**#{app_id}**|{amount:.2f}|{currency}|\n\n"
        f"Verified lenders can see and claim your application on the "
        f"[LoanCentral Dashboard]({DASHBOARD_URL}).\n\n"
        f"You'll receive a Reddit message if a lender claims your request. "
        f"Use `$apply cancel #{app_id}` to withdraw it.\n\n"
        f"*Note: Posting a loan application does not guarantee funding. "
        f"Only lend/borrow with users you trust.*"
    )
    logger.info(f"Loan application #{app_id} submitted by u/{borrower}: {amount} {currency}")

    try:
        from notifications import notify_discord
        reason_short = (reason[:80] + "…") if reason and len(reason) > 80 else (reason or "no reason")
        notify_discord(
            f"📝 **Loan Request** — u/{borrower} is seeking {amount:.2f} {currency} "
            f"(#{app_id}). Reason: {reason_short}"
        )
    except Exception as _e:
        logger.warning(f"Discord notify failed for application #{app_id}: {_e}")
