import re
import logging

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$remind"


def process_remind_command(comment):
    """
    $remind [loan_id] [optional custom message]
    Lender sends a polite payment reminder DM to their borrower.
    Only the lender of the loan can send a reminder.
    """
    if COMMAND_TRIGGER not in comment.body.lower():
        return

    match = re.search(r'\$remind\s+(\w+)(?:\s+(.+))?', comment.body, re.IGNORECASE)
    if not match:
        comment.reply(
            "Usage: `$remind [loan_id] [optional message]`\n\n"
            "Example: `$remind L001`\n"
            "Example: `$remind L001 Hey, just a friendly check-in on repayment!`"
        )
        return

    loan_id    = match.group(1)
    custom_msg = (match.group(2) or "").strip()
    lender     = comment.author.name.lower()

    from services import check_ban
    is_banned, ban_reason = check_ban(lender)
    if is_banned:
        comment.reply(f"Your account has been suspended from LoanCentral bot commands. Reason: {ban_reason}")
        return

    from services import _get_db, log_action
    conn = _get_db()
    if not conn:
        comment.reply("Error: Could not connect to the database. Please try again later.")
        return

    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, loan_id, lender, borrower, amount, amount_repaid, currency, status, due_date
            FROM loans
            WHERE (id::text = %s OR loan_id = %s) AND lender = %s
            ORDER BY id DESC LIMIT 1
        """, (loan_id, loan_id, lender))
        row = cur.fetchone()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"$remind db error for {lender}: {e}", exc_info=True)
        try: cur.close()
        except Exception: pass
        try: conn.close()
        except Exception: pass
        comment.reply("Error looking up loan. Please try again later.")
        return

    if not row:
        comment.reply(
            f"Could not find loan **{loan_id}** where you are the lender.\n\n"
            f"Use `$outstanding` to see your active loan IDs."
        )
        return

    _, public_id, _, borrower, amount, amount_repaid, currency, status, due_date = row

    if status in ("repaid", "refunded"):
        comment.reply(f"Loan {public_id} is already {status} — no reminder needed.")
        return

    remaining = float(amount) - float(amount_repaid)
    due_str   = due_date.strftime('%Y-%m-%d') if due_date else "no due date set"

    if custom_msg:
        dm_body = (
            f"{custom_msg}\n\n"
            f"---\n"
            f"**Loan reference:** {public_id} — {remaining:.2f} {currency} outstanding (due: {due_str})\n"
            f"*Sent via LoanCentral — community record-keeping tool.*"
        )
    else:
        dm_body = (
            f"Hi u/{borrower}, this is a friendly reminder from u/{lender} "
            f"regarding loan **{public_id}**.\n\n"
            f"**Outstanding balance:** {remaining:.2f} {currency}\n"
            f"**Due date:** {due_str}\n\n"
            f"Please reach out if you need to discuss repayment arrangements. Thank you!\n\n"
            f"---\n*Sent via LoanCentral — community record-keeping tool.*"
        )

    try:
        from utils import reddit
        reddit.redditor(borrower).message(
            subject=f"[LoanCentral] Payment reminder — loan {public_id}",
            message=dm_body,
        )
        log_action(lender, "reminder_sent", public_id, f"to u/{borrower} — {remaining:.2f} {currency}")
        comment.reply(
            f"Reminder sent to u/{borrower} for loan **{public_id}** "
            f"({remaining:.2f} {currency} outstanding, due: {due_str})."
        )
        logger.info(f"u/{lender} sent payment reminder for loan {public_id} to u/{borrower}")

    except Exception as e:
        logger.error(f"$remind DM failed for {lender} on {public_id}: {e}", exc_info=True)
        comment.reply(
            f"Could not send the reminder DM to u/{borrower}. "
            f"Please message them directly."
        )
