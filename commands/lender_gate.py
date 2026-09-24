"""Who may use lender commands: whoever holds the lender flair.

Owner decision, 2026-09-23 (docs/SECURITY.md rule 2): on Reddit, the
subreddit's lender flair is what grants lender commands ($loan, $fund,
$paid_with_id, $unpaid, $refunded). Anyone without it is ignored, silently —
a reply would spend an API call on someone who is not a lender, on every try.

The database still records the grant. The first time a flaired lender uses a
command, they are marked verified in user_roles (audited, granted by
"reddit-flair"), because the services re-check verification before recording a
loan. Flair is read from the comment itself, which costs no API call.

Configuration:
  LENDER_FLAIR_TEXT         flair text(s) that count, comma-separated, exact
                            match ignoring case and :emoji: codes.
                            Default "Verified Lender".
  LENDER_FLAIR_TEMPLATE_ID  optional. When set, the flair *template* must
                            match instead of the text. Stronger: a user who may
                            edit their own flair text can type "Verified
                            Lender", but cannot pick a mod-only template.
"""

import logging
import os
import re

logger = logging.getLogger("LoanCentral")

_MISSING = object()
_EMOJI_CODE = re.compile(r":[A-Za-z0-9_+-]+:")

#: Recorded as verified_lender_by / the audit actor for flair grants.
FLAIR_GRANTOR = "reddit-flair"


def _normalize_flair(text):
    return " ".join(_EMOJI_CODE.sub(" ", str(text or "")).split()).lower()


def _accepted_flair_texts():
    raw = os.getenv("LENDER_FLAIR_TEXT") or "Verified Lender"
    return {_normalize_flair(part) for part in raw.split(",") if part.strip()}


def _tier_suffixes():
    """" · gold", " · legacy"… — the ranks the bot itself writes into flair."""
    from tiers import LEGACY, LENDER_TIERS
    return {f" · {name.lower()}" for name, _ in LENDER_TIERS} | {f" · {LEGACY.lower()}"}


def _flair_matches(text, template_id):
    wanted_template = (os.getenv("LENDER_FLAIR_TEMPLATE_ID") or "").strip()
    if wanted_template:
        return (template_id or "").strip() == wanted_template
    flair = _normalize_flair(text)
    for base in _accepted_flair_texts():
        # The bare lender flair, or the bot's own ranked version of it
        # ("Verified Lender · Gold"). Only known ranks: an arbitrary suffix
        # like "Verified Lender · pending" does not count.
        if flair == base or any(flair == base + s for s in _tier_suffixes()):
            return True
    return False


def base_flair_text():
    """The lender flair as it should be written (first of LENDER_FLAIR_TEXT)."""
    raw = os.getenv("LENDER_FLAIR_TEXT") or "Verified Lender"
    return raw.split(",")[0].strip() or "Verified Lender"


def has_lender_flair(comment):
    """Return (has_flair, checked).

    `checked` is False only when the flair could not be read at all; the caller
    then falls back to the database instead of locking every lender out over a
    Reddit-side failure.
    """
    text = getattr(comment, "author_flair_text", _MISSING)
    if text is not _MISSING:
        # Present on every comment Reddit returns (None when unflaired).
        return _flair_matches(text, getattr(comment, "author_flair_template_id", None)), True
    try:
        # Objects without inline flair: ask the subreddit (moderator-only call).
        for row in comment.subreddit.flair(redditor=comment.author.name) or []:
            row = row or {}
            if _flair_matches(row.get("flair_text"), row.get("flair_template_id")):
                return True, True
        return False, True
    except Exception as exc:
        logger.error(f"Could not read lender flair for {comment.author.name}: {exc}. "
                     "Falling back to the LoanCentral verification record.")
        return False, False


def _record_flair_grant(reddit_name, subreddit_name):
    """Mark a flaired lender verified in the database, once, with an audit row."""
    from services import (get_verified_lender_status, log_audit,
                          resolve_user_identity, set_verified_lender)

    is_verified, _, err = get_verified_lender_status(reddit_name)
    if err:
        raise RuntimeError(err)
    if is_verified:
        return
    identity, _ = resolve_user_identity(reddit_name)
    username = (identity or {}).get("username") or reddit_name.lower()
    note = f"Lender flair on r/{subreddit_name}" if subreddit_name else "Lender flair on Reddit"
    ok, error = set_verified_lender(username, True, FLAIR_GRANTOR, note)
    if not ok:
        raise RuntimeError(error)
    log_audit(FLAIR_GRANTOR, "system", "verified_lender_granted", "user", username,
              new_value={"verified": True, "note": note, "reddit_username": reddit_name})
    logger.info(f"u/{reddit_name} verified as a lender from their flair")


def require_verified_lender(comment):
    """Gate for lender-only bot commands. Returns True to proceed.

    Never replies: people without the flair cannot interact with lender
    commands, and a refusal would cost an API call each time.
    """
    reddit_name = comment.author.name
    has_flair, checked = has_lender_flair(comment)

    if checked:
        if not has_flair:
            logger.info(f"Ignoring lender command from u/{reddit_name}: no lender flair")
            return False
        try:
            _record_flair_grant(reddit_name, getattr(comment.subreddit, "display_name", ""))
        except Exception as exc:
            logger.error(f"Could not record lender verification for u/{reddit_name}: {exc}")
            return False
        return True

    # Flair unreadable: fall back to the verification already on record.
    try:
        from services import get_verified_lender_status
        is_verified, _, err = get_verified_lender_status(reddit_name)
    except Exception as exc:
        logger.error(f"Error checking verified lender status for u/{reddit_name}: {exc}")
        return False
    if err or not is_verified:
        logger.info(f"Ignoring lender command from u/{reddit_name}: flair unreadable, not verified")
        return False
    return True
