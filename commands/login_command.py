"""$login — DM the commenter a one-time link to set up their dashboard account.

Anyone can use it (borrowers and lenders alike). The link goes to the
commenter's own inbox, so following it proves they own the Reddit account; it
does not sign them in, it lets them connect a Google account (accounts.py).

Success is silent in the thread: the DM is the answer, and a public reply would
add clutter and cost an API call. The bot replies only when the DM can't be
delivered, so the person knows to open their messages.

Outbound Reddit write (docs/SECURITY.md rule 4): a DM to the account that
asked for it, sent in answer to its own command — the same footing as the bot's
replies. Rate-limited per account in accounts.create_setup_link.
"""

import logging

from bot_messages import DASHBOARD_URL, with_dashboard_link

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$login"


def _setup_url(token):
    return f"{DASHBOARD_URL.rstrip('/')}/account/setup/{token}"


def _dm_body(reddit_name, token):
    from accounts import SETUP_LINK_MINUTES
    return (
        f"Hi u/{reddit_name},\n\n"
        f"Here is your LoanCentral link:\n\n{_setup_url(token)}\n\n"
        f"Open it to create your account (or reconnect it) and link a Google account "
        f"to u/{reddit_name}. After that, sign in on the dashboard with Google.\n\n"
        f"The link works once and expires in {SETUP_LINK_MINUTES} minutes. "
        "Don't share it — it's proof that you are this Reddit account. "
        "If you didn't comment !login, you can ignore this message."
    )


def _is_reddit_rate_limit(exc):
    """True when Reddit refused because the bot is sending too much
    ("RATELIMIT" / HTTP 429), as opposed to the person's message settings."""
    for item in getattr(exc, "items", None) or []:
        if getattr(item, "error_type", "") == "RATELIMIT":
            return True
    return type(exc).__name__ == "TooManyRequests" or "RATELIMIT" in str(exc).upper()


def process_login_command(comment):
    from accounts import create_setup_link

    reddit_name = comment.author.name

    # A flaired lender's account should open as a lender account: record the
    # flair grant now (the same audited path lender commands use). Without the
    # flair nothing is granted — $login itself never gives anyone lender access.
    try:
        from commands.lender_gate import _record_flair_grant, has_lender_flair
        has_flair, checked = has_lender_flair(comment)
        if checked and has_flair:
            _record_flair_grant(reddit_name, getattr(comment.subreddit, "display_name", ""))
    except Exception as exc:
        logger.error(f"$login: lender flair check failed for u/{reddit_name}: {exc}")

    token, error = create_setup_link(reddit_name)
    if error == "rate_limited":
        logger.info(f"$login rate-limited for u/{reddit_name}")
        return
    if error:
        logger.error(f"$login: could not create a setup link for u/{reddit_name}: {error}")
        return

    try:
        comment.author.message(subject="Your LoanCentral link", message=_dm_body(reddit_name, token))
        logger.info(f"$login: setup link sent to u/{reddit_name}")
    except Exception as exc:
        if _is_reddit_rate_limit(exc):
            # Reddit is limiting how many messages the bot may send right now
            # (a rush of $login at launch). Not the person's settings.
            logger.warning(f"$login: Reddit rate-limited the DM to u/{reddit_name}: {exc}")
            comment.reply(with_dashboard_link(
                f"u/{reddit_name}, lots of people are signing up right now and Reddit is "
                "limiting how many messages I can send. Comment `!login` again in about "
                "10 minutes and your link will come through."
            ))
            return
        # Typically the person only accepts messages from people they follow.
        logger.warning(f"$login: could not DM u/{reddit_name}: {exc}")
        comment.reply(with_dashboard_link(
            f"u/{reddit_name}, I couldn't send you a private message. "
            "Check that your Reddit messages are open to everyone "
            "(Settings → Chat & Messaging), then comment `$login` again."
        ))
