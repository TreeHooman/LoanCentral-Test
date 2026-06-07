import re
import logging

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$ban"


def _is_mod(comment):
    """Return True if the comment author has a Mod flair in the subreddit."""
    try:
        flair_list = list(comment.subreddit.flair(redditor=comment.author))
        flair_text = flair_list[0]["flair_text"] if flair_list else ""
        return flair_text and "mod" in flair_text.lower()
    except Exception:
        return False


def process_ban_command(comment):
    """
    $ban u/username [reason]
    Mod-only: prevents a user from using bot commands.
    """
    if COMMAND_TRIGGER not in comment.body:
        return

    if not _is_mod(comment):
        comment.reply("Only moderators can use the `$ban` command.")
        return

    match = re.search(r'\$ban\s+u?/?([\w-]+)(?:\s+(.+))?', comment.body, re.IGNORECASE)
    if not match:
        return

    target  = match.group(1).lower()
    reason  = (match.group(2) or "").strip() or "No reason provided."
    banner  = comment.author.name.lower()

    if target == banner:
        comment.reply("You cannot ban yourself.")
        return

    from services import ban_user
    success, error = ban_user(target, reason, banner)

    if not success:
        comment.reply(f"Error banning u/{target}: {error}")
        logger.error(f"$ban failed for {target} by {banner}: {error}")
        return

    comment.reply(
        f"u/{target} has been banned from using LoanCentral bot commands.\n\n"
        f"**Reason:** {reason}\n\n"
        f"*Use `$unban u/{target}` to reverse this action.*"
    )
    logger.info(f"u/{target} banned by u/{banner}: {reason}")

    try:
        from notifications import notify_discord
        notify_discord(f"🔨 **User Banned** — u/{banner} banned u/{target}: {reason[:120]}")
    except Exception as _e:
        logger.warning(f"Discord notify failed for ban: {_e}")
