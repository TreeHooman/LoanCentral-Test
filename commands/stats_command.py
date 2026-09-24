"""$stats u/name — Reddit account check lenders use before lending.

Karma, account age, and how active the account has been, from its last 100
comments. About two Reddit API calls per use (the account, one page of
comments), well inside the rate budget.

Brought back from the original bot, which printed the all-time figures on the
"Last 180 days" lines; those are now computed from the last 180 days.
"""

import logging
import re
from datetime import datetime, timedelta, timezone

from bot_messages import with_dashboard_link

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$stats"

_STATS_RE = re.compile(r"\$stats\s+/?u/([\w-]+)", re.IGNORECASE)


def _gaps(times):
    """(average days between, longest gap in days) for a list of datetimes."""
    ordered = sorted(times)
    gaps = [(b - a).total_seconds() / 86400 for a, b in zip(ordered, ordered[1:])]
    return (sum(gaps) / len(gaps), max(gaps)) if gaps else (0.0, 0.0)


def _day_gaps(times):
    days = sorted({t.date() for t in times})
    gaps = [(b - a).days for a, b in zip(days, days[1:])]
    return (sum(gaps) / len(gaps), max(gaps)) if gaps else (0.0, 0)


def build_stats(name, redditor, comments, now=None):
    """The reply text, from a redditor and its recent comments (testable offline)."""
    now = now or datetime.now(timezone.utc)
    stamp = lambda c: datetime.fromtimestamp(c.created_utc, timezone.utc)
    times = [stamp(c) for c in comments]
    recent = [t for t in times if t >= now - timedelta(days=180)]

    lines = [f"# Account statistics for u/{name}", ""]
    if times:
        avg_all, max_all = _gaps(times)
        avg_180, max_180 = _gaps(recent)
        davg_all, dmax_all = _day_gaps(times)
        davg_180, dmax_180 = _day_gaps(recent)
        lines += [
            f"**Comments scanned:** {len(times)} (last 180 days: {len(recent)})",
            f"**Newest comment:** {max(times).date()}  ",
            f"**Oldest scanned:** {min(times).date()}",
            "",
            "|Activity|All scanned|Last 180 days|",
            "|:--|--:|--:|",
            f"|Average time between comments|{avg_all:.2f} days|{avg_180:.2f} days|",
            f"|Longest time between comments|{max_all:.0f} days|{max_180:.0f} days|",
            f"|Average time between active days|{davg_all:.2f} days|{davg_180:.2f} days|",
            f"|Longest time between active days|{dmax_all} days|{dmax_180} days|",
            "",
        ]
        karma = {}
        for c in comments:
            sub = c.subreddit.display_name
            karma[sub] = karma.get(sub, 0) + (c.score or 0)
        top = sorted(karma.items(), key=lambda kv: kv[1], reverse=True)[:3]
        if top:
            lines += ["**Top subreddits by comment karma:** "
                      + ", ".join(f"r/{s} ({k})" for s, k in top), ""]
    else:
        lines += ["No comments found.", ""]

    created = datetime.fromtimestamp(redditor.created_utc, timezone.utc)
    age_days = (now - created).days
    post_k, comment_k = redditor.link_karma or 0, redditor.comment_karma or 0
    lines += [
        f"**Account age:** {age_days} days ({age_days / 365:.2f} years)  ",
        f"**Karma:** {post_k + comment_k} (post {post_k}, comment {comment_k})  ",
        f"**Verified email:** {'Yes' if getattr(redditor, 'has_verified_email', False) else 'No'}  ",
        f"**USL:** [check u/{name}](https://www.universalscammerlist.com/?username={name})",
    ]
    return "\n".join(lines)


def process_stats_command(comment):
    from utils import reddit

    match = _STATS_RE.search(comment.body or "")
    if not match:
        return
    name = match.group(1)
    try:
        redditor = reddit.redditor(name)
        comments = list(redditor.comments.new(limit=100))
        text = build_stats(name, redditor, comments)
    except Exception as exc:
        logger.warning(f"$stats for u/{name} failed: {exc}")
        comment.reply(with_dashboard_link(
            f"Couldn't fetch stats for u/{name}. The account may not exist or may be suspended."))
        return
    comment.reply(with_dashboard_link(text))
    logger.info(f"$stats sent for u/{name}")
