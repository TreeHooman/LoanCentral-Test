import logging
from datetime import datetime, timezone

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$status"


def process_status_command(comment):
    """
    $status
    Anyone can check if the bot and database are alive.
    Shows uptime, last heartbeat, and quick loan stats.
    """
    if COMMAND_TRIGGER not in comment.body.lower():
        return

    from services import get_bot_status, _get_db
    from config import DASHBOARD_URL

    username = comment.author.name

    # DB health check
    db_ok = False
    total_loans = active_loans = 0
    try:
        conn = _get_db()
        if conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*), COUNT(*) FILTER (WHERE status IN ('confirmed','partially_repaid')) FROM loans"
            )
            row = cur.fetchone()
            if row:
                total_loans, active_loans = row[0], row[1]
            cur.close()
            conn.close()
            db_ok = True
    except Exception as e:
        logger.warning(f"$status DB check failed: {e}")

    # Bot heartbeat
    bot = get_bot_status()
    if bot and bot.get("last_heartbeat"):
        hb = bot["last_heartbeat"]
        if isinstance(hb, str):
            try:
                hb = datetime.fromisoformat(hb.replace("Z", "+00:00"))
            except ValueError:
                hb = None
        if hb:
            now = datetime.now(timezone.utc)
            if hb.tzinfo is None:
                hb = hb.replace(tzinfo=timezone.utc)
            age_min = int((now - hb).total_seconds() / 60)
            hb_str = f"{age_min}m ago" if age_min < 60 else f"{age_min // 60}h {age_min % 60}m ago"
        else:
            hb_str = "unknown"
    else:
        hb_str = "no heartbeat recorded"

    db_status  = "✅ Online" if db_ok  else "❌ Unreachable"
    bot_status = "✅ Running" if (bot and bot.get("last_heartbeat")) else "⚠️ Unknown"

    comment.reply(
        f"**LoanCentral Bot Status**\n\n"
        f"|Component|Status|\n"
        f"|:--|:--|\n"
        f"|Bot|{bot_status}|\n"
        f"|Database|{db_status}|\n"
        f"|Last heartbeat|{hb_str}|\n\n"
        f"|Total Loans|Active Loans|\n"
        f"|:--:|:--:|\n"
        f"|{total_loans}|{active_loans}|\n\n"
        f"[View Dashboard]({DASHBOARD_URL})"
    )
    logger.info(f"$status requested by u/{username}")
