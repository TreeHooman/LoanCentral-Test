import re
import logging

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$dispute"


def process_dispute_command(comment):
    """
    $dispute [loan_id] [reason]
    Borrower files a dispute on a loan marked unpaid.
    Only loans with status='unpaid' can be disputed.
    """
    if COMMAND_TRIGGER not in comment.body:
        return

    match = re.search(r'\$dispute\s+(\w+)(?:\s+(.+))?', comment.body, re.IGNORECASE)
    if not match:
        comment.reply(
            "Usage: `$dispute [loan_id] [reason]`\n\n"
            "Example: `$dispute 1234567890 I repaid this loan via Venmo on Jan 5`"
        )
        return

    loan_id  = match.group(1)
    reason   = (match.group(2) or "").strip() or "No reason provided."
    borrower = comment.author.name.lower()

    from services import check_ban
    is_banned, ban_reason = check_ban(borrower)
    if is_banned:
        comment.reply(f"Your account has been suspended from LoanCentral bot commands. Reason: {ban_reason}")
        return

    from services import submit_dispute
    dispute_id, error = submit_dispute(loan_id, borrower, reason)

    if error:
        comment.reply(f"Could not file dispute: {error}")
        logger.warning(f"$dispute failed for u/{borrower} on loan {loan_id}: {error}")
        return

    comment.reply(
        f"Your dispute (#{dispute_id}) has been filed and the moderators have been notified.\n\n"
        f"**Loan ID:** {loan_id}\n"
        f"**Reason:** {reason}\n\n"
        f"*Moderators will review and contact you. Please do not re-submit.*"
    )
    logger.info(f"u/{borrower} filed dispute #{dispute_id} on loan {loan_id}")

    try:
        for sub_name in __import__('os').getenv("SUBREDDITS", "").split(","):
            sub_name = sub_name.strip()
            if sub_name:
                from utils import reddit
                reddit.subreddit(sub_name).message(
                    subject=f"[LoanCentral] Dispute #{dispute_id} — u/{borrower}",
                    message=(
                        f"**Borrower:** u/{borrower}\n"
                        f"**Loan ID:** {loan_id}\n"
                        f"**Reason:** {reason}\n\n"
                        f"**Thread:** https://www.reddit.com{comment.permalink}"
                    ),
                )
    except Exception as _e:
        logger.warning(f"Modmail send failed for dispute #{dispute_id}: {_e}")

    try:
        from notifications import notify_discord
        reason_short = (reason[:100] + "…") if len(reason) > 100 else reason
        notify_discord(
            f"⚖️ **Dispute #{dispute_id}** — u/{borrower} disputed loan {loan_id}: {reason_short}"
        )
    except Exception as _e:
        logger.warning(f"Discord notify failed for dispute #{dispute_id}: {_e}")
