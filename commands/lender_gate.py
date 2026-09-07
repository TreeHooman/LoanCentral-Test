import logging
import os

from bot_messages import with_dashboard_link

logger = logging.getLogger("LoanCentral")


def _flair_gate_enabled():
    """Whether the optional Reddit-flair gate runs on top of the DB check.

    Off by default: docs/SECURITY.md rule 2 makes the DB the source of truth for
    permissions, and reading flair costs a moderator-only API call that denies
    every lender at once if the bot loses mod status.
    """
    return (os.getenv("REQUIRE_LENDER_FLAIR") or "").strip().lower() in ("1", "true", "yes", "on")


def _has_verified_lender_flair(comment):
    """Check the operational Reddit flair.

    Returns (has_flair, checked) — `checked` is False when the flair could not
    be read at all, in which case the caller keeps the DB decision instead of
    locking the lender out over a Reddit-side failure.
    """
    try:
        flair_rows = comment.subreddit.flair(redditor=comment.author.name)
        for row in flair_rows or []:
            flair_text = str((row or {}).get("flair_text") or "").strip().lower()
            if "verified lender" in flair_text:
                return True, True
        return False, True
    except Exception as exc:
        # Typically a 403 when the bot is not a moderator of this subreddit, or
        # a transient API error. Either way it says nothing about the lender.
        logger.error(
            f"Could not read lender flair for {comment.author.name} in "
            f"r/{getattr(comment.subreddit, 'display_name', '?')}: {exc}. "
            "Falling back to the LoanCentral DB verification result."
        )
        return False, False


def require_verified_lender(comment):
    """
    Gate for lender-only bot commands.

    The LoanCentral DB is the granting authority. The Reddit flair check is an
    optional extra restriction, enabled with REQUIRE_LENDER_FLAIR=1.
    """
    reddit_name = comment.author.name

    try:
        from services import get_verified_lender_status

        is_verified, _, err = get_verified_lender_status(reddit_name)
        if err:
            raise RuntimeError(err)
        if not is_verified:
            comment.reply(with_dashboard_link(
                "Error: Your account has not completed the LoanCentral lender verification process. "
                "Contact a moderator to begin the process."
            ))
            return False
    except Exception as exc:
        logger.error(f"Error checking verified lender status for {reddit_name}: {exc}")
        comment.reply(with_dashboard_link(
            "Error: Unable to verify your lender status. Please contact the moderators."
        ))
        return False

    if _flair_gate_enabled():
        has_flair, checked = _has_verified_lender_flair(comment)
        if checked and not has_flair:
            comment.reply(with_dashboard_link(
                "Error: Your Reddit account is missing the Verified Lender flair required for lender commands. "
                "Please contact the moderators after your LoanCentral verification is approved."
            ))
            return False

    return True
