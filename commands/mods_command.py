"""$mods [message] — anyone can ask the moderators to look at a thread.

Sends one modmail with the thread link and the message. Limited to
MODS_PER_HOUR per person, so it can't be used to flood modmail.
"""

import logging
import re
import time

from bot_messages import with_dashboard_link

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$mods"
MODS_PER_HOUR = 3

_recent = {}


def _allowed(name):
    now = time.time()
    hits = [t for t in _recent.get(name, []) if now - t < 3600]
    if len(hits) >= MODS_PER_HOUR:
        _recent[name] = hits
        return False
    _recent[name] = hits + [now]
    return True


def process_mods_command(comment):
    name = comment.author.name
    if not _allowed(name.lower()):
        logger.info(f"$mods rate-limited for u/{name}")
        return
    match = re.search(r"\$mods\b\s*(.*)", comment.body or "", re.IGNORECASE | re.DOTALL)
    note = (match.group(1).strip() if match else "")[:1500] or "No message given."
    submission = getattr(comment, "submission", None)
    permalink = getattr(comment, "permalink", "") or ""
    try:
        comment.subreddit.message(
            subject=f"Moderator request from u/{name}",
            message=(f"**User:** u/{name}\n\n"
                     f"**Thread:** https://www.reddit.com{permalink}\n\n"
                     f"**Post:** {getattr(submission, 'title', '')}\n\n"
                     f"**Message:**\n\n{note}\n\n"
                     "---\nSent by the LoanCentral bot in answer to $mods."))
    except Exception as exc:
        logger.error(f"$mods modmail failed for u/{name}: {exc}")
        comment.reply(with_dashboard_link(
            "Couldn't reach the moderators just now. Please message them directly."))
        return
    comment.reply(with_dashboard_link(
        f"Thanks u/{name}, I've let the moderators know. They'll take a look as soon as they can."))
    logger.info(f"$mods sent for u/{name}")
