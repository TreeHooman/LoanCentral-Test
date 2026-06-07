import re
import logging

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$request"


def process_request_command(comment):
    """
    $request lender [optional reason]
    Lets a user submit a request to be granted lender access.
    Mods approve/deny on the dashboard.
    """
    from config import DASHBOARD_URL

    match = re.search(
        r'\$request\s+(lender|mod)(?:\s+(.+))?',
        comment.body,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        comment.reply(
            "Usage: `$request lender [reason]`\n\n"
            "Example: `$request lender I have been lending on r/borrow for 2 years`"
        )
        return

    requested_role = match.group(1).lower()
    reason = (match.group(2) or "").strip()[:500]
    username = comment.author.name.lower()

    # Only lender requests accepted via bot — mod grants stay on dashboard
    if requested_role == "mod":
        comment.reply("Mod requests must be submitted directly to the subreddit moderators.")
        return

    from services import get_user_role, submit_role_request
    current_role, _ = get_user_role(username)
    if current_role in ("lender", "mod"):
        comment.reply(
            f"You already have **{current_role}** access on LoanCentral. "
            f"No request needed!"
        )
        return

    ok, error = submit_role_request(username, requested_role, reason)
    if error:
        comment.reply(f"Error submitting request: {error}")
        logger.error(f"$request failed for u/{username}: {error}")
        return

    comment.reply(
        f"Your request for **lender** access has been submitted!\n\n"
        f"A moderator will review your account history and get back to you. "
        f"There is no fixed timeline, but requests are typically reviewed within a few days.\n\n"
        f"In the meantime, you can check your borrower profile on the "
        f"[LoanCentral Dashboard]({DASHBOARD_URL})."
    )
    logger.info(f"Lender role request submitted by u/{username}: {reason[:50] if reason else '(no reason)'}")
