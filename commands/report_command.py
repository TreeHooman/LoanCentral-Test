import re
import logging
import os

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$report"


def process_report_command(comment):
    """
    $report u/username [reason]
    Anyone can file a report — mods are DM'd via subreddit modmail.
    """
    match = re.search(r'\$report\s+u?/?([\w-]+)(?:\s+(.+))?', comment.body, re.IGNORECASE)
    if not match:
        return

    reported = match.group(1).lower()
    reason   = (match.group(2) or "No reason provided.").strip()
    reporter = comment.author.name

    if reported == reporter.lower():
        comment.reply("You cannot report yourself.")
        return

    try:
        from utils import reddit
        for sub in os.getenv("SUBREDDITS", "").split(","):
            sub = sub.strip()
            if sub:
                reddit.subreddit(sub).message(
                    subject=f"[LoanCentral] Report: u/{reported}",
                    message=(
                        f"**Filed by:** u/{reporter}\n"
                        f"**Reported user:** u/{reported}\n"
                        f"**Reason:** {reason}\n\n"
                        f"**Thread:** https://www.reddit.com{comment.permalink}"
                    ),
                )
        comment.reply(
            f"Report submitted. The moderators will review u/{reported}.\n\n"
            f"*If this is urgent, please also send a modmail directly.*"
        )
        logger.info(f"u/{reporter} reported u/{reported}: {reason}")
    except Exception as e:
        logger.error(f"Failed to send report from {reporter}: {e}")
        comment.reply("Error submitting report. Please contact the mods via modmail directly.")
