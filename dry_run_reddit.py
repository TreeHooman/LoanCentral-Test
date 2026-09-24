"""
Dry-run stand-in for the live praw.Reddit client.

Activated by setting REDDIT_MODE=dry_run (see utils.py). Every outbound Reddit
action (modmail, replies via objects created here) is logged with a [DRY-RUN]
prefix and captured in `outbox` instead of hitting the Reddit API. Database and
command logic run exactly as in production.

Only the small slice of the PRAW surface the bot actually uses is implemented.
Anything else raises AttributeError on purpose - better to fail loudly than to
silently pretend an unmocked API call succeeded.
"""

import logging
import time

logger = logging.getLogger("LoanCentral")


class DryRunStream:
    """Stream endpoints that never yield - keeps main.py's monitor loops idle."""

    def __init__(self, display_name):
        self._display_name = display_name

    def comments(self, skip_existing=False, pause_after=None):
        logger.info(f"[DRY-RUN] comment stream for r/{self._display_name} requested - idling, no Reddit connection")
        while True:
            # Like PRAW with pause_after set: report "nothing new" now and then,
            # so the bot's heartbeat keeps going offline too.
            time.sleep(3600 if pause_after is None else 30)
            if pause_after is not None:
                yield None

    def submissions(self, skip_existing=False, pause_after=None):
        logger.info(f"[DRY-RUN] post stream for r/{self._display_name} requested - idling, no Reddit connection")
        while True:
            # Like PRAW with pause_after set: report "nothing new" now and then,
            # so the bot's heartbeat keeps going offline too.
            time.sleep(3600 if pause_after is None else 30)
            if pause_after is not None:
                yield None


class DryRunSubreddit:
    def __init__(self, display_name, outbox):
        self.display_name = display_name
        self.stream = DryRunStream(display_name)
        self._outbox = outbox

    def flair(self, redditor=None):
        # No flair in dry-run: the DB gate in lender_gate still runs first, and
        # returning no flair keeps the dual gate honest instead of waving
        # everyone through. The simulator overrides this per-user.
        logger.info(f"[DRY-RUN] flair lookup for u/{redditor} in r/{self.display_name} -> none (stubbed)")
        return []

    def message(self, subject, message):
        self._outbox.append(
            {
                "type": "modmail",
                "subreddit": self.display_name,
                "subject": subject,
                "message": message,
            }
        )
        logger.info(f"[DRY-RUN] modmail to r/{self.display_name} | subject: {subject}\n{message}")


class DryRunRedditor:
    def __init__(self, name):
        self.name = name


class DryRunReddit:
    """Drop-in replacement for the praw.Reddit singleton in utils.py."""

    def __init__(self):
        self.outbox = []
        self._subreddits = {}

    def subreddit(self, display_name):
        if display_name not in self._subreddits:
            self._subreddits[display_name] = DryRunSubreddit(display_name, self.outbox)
        return self._subreddits[display_name]

    def redditor(self, name):
        return DryRunRedditor(name)
