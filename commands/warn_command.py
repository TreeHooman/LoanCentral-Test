import re
import logging

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$warn"


def _is_mod(comment):
    try:
        flair_list = list(comment.subreddit.flair(redditor=comment.author))
        flair_text = flair_list[0]["flair_text"] if flair_list else ""
        return flair_text and "mod" in flair_text.lower()
    except Exception:
        return False


def process_warn_command(comment):
    """
    $warn u/username [reason]
    Mod-only: sends a formal warning DM to a user and logs it as a mod note.
    """
    if COMMAND_TRIGGER not in comment.body:
        return

    if not _is_mod(comment):
        comment.reply("Only moderators can use the `$warn` command.")
        return

    match = re.search(r'\$warn\s+u?/?([\w-]+)(?:\s+(.+))?', comment.body, re.IGNORECASE | re.DOTALL)
    if not match:
        comment.reply("Usage: `$warn u/username [reason]`")
        return

    target  = match.group(1).lower()
    reason  = (match.group(2) or "").strip() or "Violation of community rules."
    mod     = comment.author.name.lower()

    if target == mod:
        comment.reply("You cannot warn yourself.")
        return

    # Log as a mod note
    from services import add_mod_note, log_action
    note_text = f"⚠️ Warning issued: {reason}"
    add_mod_note(target, note_text, mod)
    log_action(mod, "warn_issued", target, reason[:200])

    # DM the user
    dm_sent = False
    try:
        from utils import reddit
        from config import DASHBOARD_URL
        reddit.redditor(target).message(
            subject="[LoanCentral] Formal Warning",
            message=(
                f"Hi u/{target},\n\n"
                f"You have received a formal warning from the LoanCentral moderators.\n\n"
                f"**Reason:** {reason}\n\n"
                f"Please review the community rules. Further violations may result in a ban.\n\n"
                f"If you believe this is in error, please send a modmail.\n\n"
                f"[View your loans on LoanCentral Dashboard]({DASHBOARD_URL})"
            ),
        )
        dm_sent = True
        logger.info(f"Warning DM sent to u/{target} by u/{mod}")
    except Exception as e:
        logger.error(f"Failed to DM warning to u/{target}: {e}")

    dm_note = "" if dm_sent else "\n\n*Note: DM could not be delivered — user may have DMs disabled.*"

    comment.reply(
        f"⚠️ Warning issued to u/{target}.\n\n"
        f"**Reason:** {reason}\n\n"
        f"A DM has been sent and this warning has been logged to their mod notes.{dm_note}"
    )
    logger.info(f"u/{mod} warned u/{target}: {reason}")

    try:
        from notifications import notify_discord
        notify_discord(f"⚠️ **Warning Issued** — u/{mod} warned u/{target}: {reason[:120]}")
    except Exception as _e:
        logger.warning(f"Discord notify failed for warning: {_e}")
