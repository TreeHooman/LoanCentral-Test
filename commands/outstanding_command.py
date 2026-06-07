import logging

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$outstanding"


def process_outstanding_command(comment):
    """
    $outstanding
    Shows the lender all their currently active/partially-repaid loans
    with amounts still owed. Quick way to see who hasn't paid back yet.
    """
    if COMMAND_TRIGGER not in comment.body.lower():
        return

    lender = comment.author.name.lower()
    from services import _get_db
    from config import DASHBOARD_URL

    conn = _get_db()
    if not conn:
        comment.reply("Error: Could not connect to the database. Please try again later.")
        return

    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT loan_id, borrower, amount, amount_repaid, currency, status, due_date
            FROM loans
            WHERE lender = %s AND status IN ('confirmed', 'partially_repaid')
            ORDER BY date_created ASC
        """, (lender,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"$outstanding error for {lender}: {e}", exc_info=True)
        try: cur.close()
        except Exception: pass
        try: conn.close()
        except Exception: pass
        comment.reply("Error fetching outstanding loans. Please try again later.")
        return

    if not rows:
        comment.reply(
            f"You have no outstanding loans. All caught up! ✅\n\n"
            f"[View full history on LoanCentral Dashboard]({DASHBOARD_URL})"
        )
        logger.info(f"$outstanding: no active loans for u/{lender}")
        return

    total_out = sum(float(r[2]) - float(r[3]) for r in rows)

    table = (
        f"**Outstanding loans for u/{lender}** — {len(rows)} active, ${total_out:.2f} total owed\n\n"
        f"|Loan ID|Borrower|Owed|Currency|Status|Due|\n"
        f"|:--:|:--:|:--:|:--:|:--:|:--:|\n"
    )
    for r in rows:
        loan_id, borrower, amount, repaid, currency, status, due_date = r
        owed = float(amount) - float(repaid)
        due_str = due_date.strftime('%Y-%m-%d') if due_date else "—"
        status_str = "Active" if status == "confirmed" else "Partial"
        table += f"|{loan_id}|u/{borrower}|{owed:.2f}|{currency}|{status_str}|{due_str}|\n"

    table += f"\n[Full history on LoanCentral Dashboard]({DASHBOARD_URL})"
    comment.reply(table)
    logger.info(f"$outstanding: {len(rows)} active loans for u/{lender}")
