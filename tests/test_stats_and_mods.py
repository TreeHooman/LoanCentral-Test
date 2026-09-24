"""$stats (Reddit account check) and $mods (modmail), brought back from the original bot."""

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from commands import mods_command
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


class _Sub:
    def __init__(self):
        self.sent = []

    def message(self, subject=None, message=None):
        self.sent.append((subject, message))


class ModsTests(unittest.TestCase):
    def setUp(self):
        mods_command._recent.clear()

    def run_mods(self, body="$mods please look, lender isn't answering", name="asker"):
        sub = _Sub()
        comment = SimpleNamespace(body=body, author=SimpleNamespace(name=name), subreddit=sub,
                                  permalink="/r/loancentral/comments/p/x/c1/",
                                  submission=SimpleNamespace(title="[REQ] ($100)"), replies=[])
        comment.reply = comment.replies.append
        mods_command.process_mods_command(comment)
        return sub, comment

    def test_sends_one_modmail_with_the_thread_and_message(self):
        sub, comment = self.run_mods()
        self.assertEqual(len(sub.sent), 1)
        self.assertIn("u/asker", sub.sent[0][0])
        self.assertIn("lender isn't answering", sub.sent[0][1])
        self.assertIn("/r/loancentral/comments/p/x/c1/", sub.sent[0][1])
        self.assertIn("let the moderators know", comment.replies[0])

    def test_limited_per_person_per_hour(self):
        sent = sum(len(self.run_mods()[0].sent) for _ in range(5))
        self.assertEqual(sent, mods_command.MODS_PER_HOUR)
