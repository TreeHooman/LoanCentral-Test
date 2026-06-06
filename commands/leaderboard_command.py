import logging

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$leaderboard"


def process_leaderboard_command(comment):
    """
    $leaderboard
    Posts two leaderboards in one reply:
    1. Top 5 lenders by total amount lent
    2. Top 5 borrowers by repayment rate (amount_repaid / amount_borrowed, min 2 loans)
    """
    from config import DASHBOARD_URL

    if COMMAND_TRIGGER not in comment.body:
        return

    username = comment.author.name.lower()
    logger.info(f"$leaderboard requested by u/{username}")

    def _get_db():
        from utils import get_db_connection
        return get_db_connection()

    conn = _get_db()
    if not conn:
        comment.reply("Error: Could not connect to the database. Please try again later.")
        return

    try:
        cur = conn.cursor()

        # --- Top lenders ---
        cur.execute(
            "SELECT username, loans_as_lender, amount_lent "
            "FROM users WHERE loans_as_lender > 0 "
            "ORDER BY amount_lent DESC LIMIT 5"
        )
        lenders = cur.fetchall()

        # --- Top borrowers by repayment rate ---
        cur.execute(
            "SELECT username, loans_as_borrower, amount_borrowed, amount_repaid "
            "FROM users WHERE loans_as_borrower >= 2 AND amount_borrowed > 0 "
            "ORDER BY (amount_repaid / amount_borrowed) DESC LIMIT 5"
        )
        borrowers = cur.fetchall()

        cur.close()
        conn.close()

    except Exception as e:
        logger.error(f"$leaderboard DB error: {e}", exc_info=True)
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
        comment.reply("Error: Could not retrieve leaderboard data. Please try again later.")
        return

    # --- Build lenders table ---
    if lenders:
        lenders_table = (
            "**Top Lenders**\n"
            "|Rank|Lender|Loans|Total Lent|\n"
            "|:--:|:--:|:--:|:--:|\n"
        )
        for rank, row in enumerate(lenders, start=1):
            lenders_table += f"|{rank}|u/{row[0]}|{row[1]}|${float(row[2]):.2f}|\n"
    else:
        lenders_table = "**Top Lenders**\n\nNo data yet."

    # --- Build borrowers table ---
    if borrowers:
        borrowers_table = (
            "**Top Borrowers by Repayment Rate**\n"
            "|Rank|Borrower|Loans|Repayment Rate|\n"
            "|:--:|:--:|:--:|:--:|\n"
        )
        for rank, row in enumerate(borrowers, start=1):
            username_b, loans, borrowed, repaid = row[0], row[1], float(row[2]), float(row[3])
            rate = round((repaid / borrowed) * 100, 1) if borrowed > 0 else 0.0
            borrowers_table += f"|{rank}|u/{username_b}|{loans}|{rate}%|\n"
    else:
        borrowers_table = "**Top Borrowers by Repayment Rate**\n\nNo data yet."

    reply_body = (
        f"{lenders_table}\n\n"
        f"{borrowers_table}\n\n"
        f"[View full stats on LoanCentral Dashboard]({DASHBOARD_URL})"
    )

    comment.reply(reply_body)
