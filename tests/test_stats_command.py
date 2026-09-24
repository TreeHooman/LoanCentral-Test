"""$stats (Reddit account check), brought back from the original bot."""

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from commands.stats_command import build_stats

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


def _c(days_ago, sub="loans", score=2):
    return SimpleNamespace(created_utc=(NOW - timedelta(days=days_ago)).timestamp(),
                           subreddit=SimpleNamespace(display_name=sub), score=score)


class StatsTests(unittest.TestCase):
    redditor = SimpleNamespace(created_utc=(NOW - timedelta(days=730)).timestamp(),
                               link_karma=100, comment_karma=900, has_verified_email=True)

    def test_last_180_days_is_really_the_last_180_days(self):
        # One comment a day for the last 10 days, then one 400 days ago. The old
        # bot showed the all-time figures on the "last 180 days" lines.
        comments = [_c(d) for d in range(10)] + [_c(400)]
        text = build_stats("someone", self.redditor, comments, now=NOW)
        self.assertIn("|Longest time between comments|391 days|1 days|", text)
        self.assertIn("(last 180 days: 10)", text)

    def test_account_facts(self):
        text = build_stats("someone", self.redditor, [_c(1, "loans", 5), _c(2, "pics", 1)], now=NOW)
        self.assertIn("**Account age:** 730 days (2.00 years)", text)
        self.assertIn("**Karma:** 1000 (post 100, comment 900)", text)
        self.assertIn("r/loans (5)", text)
        self.assertIn("universalscammerlist.com/?username=someone", text)

    def test_an_account_with_no_comments(self):
        self.assertIn("No comments found", build_stats("quiet", self.redditor, [], now=NOW))
