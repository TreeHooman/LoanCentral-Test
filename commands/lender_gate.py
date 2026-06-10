import logging

from bot_messages import with_dashboard_link

logger = logging.getLogger("LoanCentral")


def _has_verified_lender_flair(comment):
    """Require the operational Reddit flair gate in addition to DB verification."""
    try:
        flair_rows = comment.subreddit.flair(redditor=comment.author.name)
        for row in flair_rows or []:
            flair_text = str((row or {}).get("flair_text") or "").strip().lower()
            if "verified lender" in flair_text:
                return True, None
        return False, None
    except Exception as exc:
        logger.error(f"Error checking lender flair for {comment.author.name}: {exc}")
        return False, "Unable to verify your Reddit lender flair right now. Please contact the moderators."


def require_verified_lender(comment):
    """
    Dual gate for lender-only bot commands:
    1. verified_lender in LoanCentral DB
    2. operational Verified Lender flair on Reddit
    """
    lender = comment.author.name.lower()

    try:
        from services import get_verified_lender_status

        is_verified, _, err = get_verified_lender_status(lender)
        if err:
            raise RuntimeError(err)
        if not is_verified:
            comment.reply(with_dashboard_link(
                "Error: Your account has not completed the LoanCentral lender verification process. "
                "Contact a moderator to begin the process."
            ))
            return False
    except Exception as exc:
        logger.error(f"Error checking verified lender status for {lender}: {exc}")
        comment.reply(with_dashboard_link(
            "Error: Unable to verify your lender status. Please contact the moderators."
        ))
        return False

    has_flair, flair_error = _has_verified_lender_flair(comment)
    if flair_error:
        comment.reply(with_dashboard_link(f"Error: {flair_error}"))
        return False
    if not has_flair:
        comment.reply(with_dashboard_link(
            "Error: Your Reddit account is missing the Verified Lender flair required for lender commands. "
            "Please contact the moderators after your LoanCentral verification is approved."
        ))
        return False

    return True
