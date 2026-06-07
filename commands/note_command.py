import re
import logging

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$note"


def _is_mod(comment):
    try:
        flair_list = list(comment.subreddit.flair(redditor=comment.author))
        flair_text = flair_list[0]["flair_text"] if flair_list else ""
        return flair_text and "mod" in flair_text.lower()
    except Exception:
        return False


def process_note_command(comment):
    """
    $note u/username [note text]
    Mod-only: add an internal note about a user (not visible to the user).
    Used for tracking warning history, context for future mods, etc.
    """
    if COMMAND_TRIGGER not in comment.body:
        return

    if not _is_mod(comment):
        comment.reply("Only moderators can use the `$note` command.")
        return

    match = re.search(r'\$note\s+u?/?([\w-]+)\s+(.+)', comment.body, re.IGNORECASE | re.DOTALL)
    if not match:
        comment.reply("Usage: `$note u/username [note text]`")
        return

    target  = match.group(1).lower()
    note    = match.group(2).strip()
    mod     = comment.author.name.lower()

    if not note:
        comment.reply("Please include a note after the username.")
        return

    from services import add_mod_note
    note_id, error = add_mod_note(target, note, mod)

    if error:
        comment.reply(f"Error saving note: {error}")
        logger.error(f"$note failed for {target} by {mod}: {error}")
        return

    comment.reply(
        f"Note #{note_id} saved for u/{target}.\n\n"
        f"*This note is only visible to moderators.*"
    )
    logger.info(f"u/{mod} added note #{note_id} for u/{target}")
