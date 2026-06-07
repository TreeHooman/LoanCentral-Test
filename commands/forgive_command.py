import re
import logging

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$forgive"


def process_forgive_command(comment):
    """
    $forgive [loan_id]
    Lender forgives/waives a loan — marks it as refunded.
    The loan's debt is wiped from the borrower's record.
    """
    if COMMAND_TRIGGER not in comment.body:
        return

    match = re.search(r'\$forgive\s+(\w+)', comment.body, re.IGNORECASE)
    if not match:
        return

    loan_id = match.group(1)
    lender  = comment.author.name.lower()

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
        cur.execute(
            """
            SELECT id, loan_id, lender, borrower, amount, amount_repaid, currency, status
            FROM loans
            WHERE (id::text = %s OR loan_id = %s) AND lender = %s
            ORDER BY id DESC LIMIT 1
            """,
            (loan_id, loan_id, lender),
        )
        row = cur.fetchone()
        if not row:
            comment.reply(
                f"Could not find an active loan with ID **{loan_id}** where you are the lender."
            )
            return

        db_id, public_id, _, borrower, amount, amount_repaid, currency, status = row

        if status in ("repaid", "refunded"):
            comment.reply(f"Loan {public_id} is already {status} and cannot be forgiven.")
            return

        cur.execute(
            "UPDATE loans SET status = 'refunded', last_updated = NOW() WHERE id = %s",
            (db_id,)
        )
        # Clear the unpaid mark on the borrower's record if status was unpaid
        if status == "unpaid":
            cur.execute("""
                UPDATE users
                SET unpaid_loans   = GREATEST(unpaid_loans - 1, 0),
                    unpaid_amount  = GREATEST(unpaid_amount - %s, 0),
                    last_updated   = NOW()
                WHERE username = %s
            """, (amount - amount_repaid, borrower))

        conn.commit()
        log_action(lender, "loan_forgiven", public_id, f"u/{borrower} {amount} {currency}")
        cur.close()
        conn.close()

    except Exception as e:
        logger.error(f"$forgive error: {e}", exc_info=True)
        try:
            conn.rollback()
            cur.close()
            conn.close()
        except Exception:
            pass
        comment.reply("Error processing forgiveness. Please try again later.")
        return

    remaining = float(amount) - float(amount_repaid)
    comment.reply(
        f"u/{lender} has forgiven u/{borrower}'s loan of **{float(amount):.2f} {currency}**.\n\n"
        f"The remaining balance of **{remaining:.2f} {currency}** has been waived.\n\n"
        f"*This loan has been marked as refunded and removed from active debt.*"
    )
    logger.info(f"u/{lender} forgave loan {public_id} to u/{borrower}: {amount} {currency}")

    try:
        from notifications import notify_discord
        notify_discord(
            f"💚 **Loan Forgiven** — u/{lender} forgave u/{borrower}'s loan "
            f"of {float(amount):.2f} {currency} (#{public_id})"
        )
    except Exception as _e:
        logger.warning(f"Discord notify failed for forgiveness {public_id}: {_e}")
