import logging

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$leaderboard"
DASHBOARD_URL = "https://loancentral.app"


def process_leaderboard_command(comment):
    """
    $leaderboard — show top lenders and most reliable borrowers.
    """
    from services import _get_db

    conn = _get_db()
    if not conn:
        comment.reply("Error: Database unavailable. Try again later.")
        return

    try:
        cur = conn.cursor()

        # Top lenders by total amount lent
        cur.execute("""
            SELECT lender, COUNT(*) AS loans, COALESCE(SUM(amount),0) AS total
            FROM loans WHERE status NOT IN ('refunded')
            GROUP BY lender ORDER BY total DESC LIMIT 5
        """)
        top_lenders = cur.fetchall()

        # Most reliable borrowers (>= 2 loans, 0 unpaid)
        cur.execute("""
            SELECT borrower,
                   COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE status = 'repaid') AS repaid,
                   COUNT(*) FILTER (WHERE status = 'unpaid') AS unpaid
            FROM loans
            GROUP BY borrower
            HAVING COUNT(*) >= 2 AND COUNT(*) FILTER (WHERE status = 'unpaid') = 0
            ORDER BY repaid DESC LIMIT 5
        """)
        top_borrowers = cur.fetchall()

    except Exception as e:
        logger.error(f"leaderboard error: {e}")
        comment.reply("Error fetching leaderboard data.")
        return
    finally:
        cur.close()
        conn.close()

    parts = ["## LoanCentral Leaderboard\n"]

    if top_lenders:
        parts.append("### Top Lenders\n\n|Lender|Loans|Total Lent|\n|:--|:--:|--:|\n")
        for r in top_lenders:
            parts.append(f"|u/{r[0]}|{r[1]}|${float(r[2]):,.2f}|\n")
    else:
        parts.append("*No lending activity yet.*\n")

    parts.append("\n")

    if top_borrowers:
        parts.append("### Most Reliable Borrowers\n\n|Borrower|Loans|Repaid|Unpaid|\n|:--|:--:|:--:|:--:|\n")
        for r in top_borrowers:
            parts.append(f"|u/{r[0]}|{r[1]}|{r[2]}|{r[3]}|\n")
    else:
        parts.append("*Not enough history to rank borrowers yet.*\n")

    parts.append(f"\n*Full stats: [{DASHBOARD_URL}]({DASHBOARD_URL})*")

    comment.reply("".join(parts))
    logger.info(f"$leaderboard requested by u/{comment.author.name}")
