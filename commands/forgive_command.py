import re
import logging

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$forgive"
DASHBOARD_URL = "https://loancentral.app"


def process_forgive_command(comment):
    """
    $forgive [loan_id] — lender writes off the remaining balance (marks as repaid).
    This does not penalize the borrower — use $unpaid for defaults.
    """
    from services import _get_db, update_last_login
    from datetime import datetime

    match = re.search(r'\$forgive\s+([\w-]+)', comment.body, re.IGNORECASE)
    if not match:
        return

    loan_id = match.group(1).strip()
    lender  = comment.author.name.lower()
    update_last_login(lender)

    conn = _get_db()
    if not conn:
        comment.reply("Error: Database unavailable.")
        return

    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, loan_id, borrower, amount, amount_repaid, currency, status
            FROM loans
            WHERE (id::text = %s OR loan_id = %s) AND lender = %s
            ORDER BY id DESC LIMIT 1
        """, (loan_id, loan_id, lender))
        row = cur.fetchone()

        if not row:
            comment.reply(f"Loan `{loan_id}` not found in your loans.")
            return

        db_id, public_id, borrower, amount, repaid, currency, status = row

        if status in ('repaid', 'refunded'):
            comment.reply(f"Loan `{loan_id}` is already closed (status: {status}).")
            return

        # Mark as repaid without updating borrower stats (it's forgiven, not a default)
        cur.execute("""
            UPDATE loans SET amount_repaid = amount, status = 'repaid', last_updated = %s
            WHERE id = %s
        """, (datetime.now(), db_id))
        conn.commit()

        remaining = float(amount) - float(repaid)
        comment.reply(
            f"✓ Loan `{public_id}` forgiven — {remaining:.2f} {currency} written off.\n\n"
            f"u/{borrower}'s health score is not affected.\n\n"
            f"*[Dashboard]({DASHBOARD_URL})*"
        )
        logger.info(f"$forgive: u/{lender} forgave {remaining:.2f} {currency} on loan {public_id} for u/{borrower}")

    except Exception as e:
        conn.rollback()
        logger.error(f"forgive_command error: {e}", exc_info=True)
        comment.reply(f"Error: {e}")
    finally:
        cur.close()
        conn.close()
