import re
import logging

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$unban"


def _is_mod(comment):
    try:
        flair_list = list(comment.subreddit.flair(redditor=comment.author))
        flair_text = flair_list[0]["flair_text"] if flair_list else ""
        return flair_text and "mod" in flair_text.lower()
    except Exception:
        return False


def process_unban_command(comment):
    """
    $unban u/username
    Mod-only: lifts a bot ban from a user.
    """
    if COMMAND_TRIGGER not in comment.body:
        return

    if not _is_mod(comment):
        comment.reply("Only moderators can use the `$unban` command.")
        return

    match = re.search(r'\$unban\s+u?/?([\w-]+)', comment.body, re.IGNORECASE)
    if not match:
        return

    target   = match.group(1).lower()
    unbanner = comment.author.name.lower()

    from services import unban_user
    success, error = unban_user(target, unbanner)

    if not success:
        comment.reply(f"Could not unban u/{target}: {error}")
        return

    comment.reply(f"u/{target} has been unbanned and may use LoanCentral bot commands again.")
    logger.info(f"u/{target} unbanned by u/{unbanner}")

    try:
        from notifications import notify_discord
        notify_discord(f"✅ **User Unbanned** — u/{unbanner} unbanned u/{target}")
    except Exception as _e:
        logger.warning(f"Discord notify failed for unban: {_e}")
