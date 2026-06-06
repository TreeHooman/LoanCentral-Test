import importlib
import sys
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from tests.support.fakes import (
    FakeComment,
    FakeDb,
    FakeReddit,
    FakeRedditComment,
    FakeRedditor,
    fake_utils_module,
)


class StatsCommandTests(unittest.TestCase):
    def run_stats_command(self, reddit, body="$stats u/borrower"):
        with patch.dict(sys.modules, {"utils": fake_utils_module(FakeDb(), reddit=reddit)}):
            stats_command = importlib.import_module("commands.stats_command")
            comment = FakeComment(body=body, author_name="lender")
            stats_command.process_stats_command(comment)
            return comment

    def test_stats_report_uses_fake_reddit_history(self):
        now = datetime.now(UTC)
        redditor = FakeRedditor(
            comments=[
                FakeRedditComment((now - timedelta(days=2)).timestamp(), score=5, subreddit_name="Borrow"),
                FakeRedditComment((now - timedelta(days=1)).timestamp(), score=3, subreddit_name="LoanCentral"),
            ],
            link_karma=11,
            comment_karma=22,
            created_utc=(now - timedelta(days=365)).timestamp(),
            has_verified_email=False,
        )
        reddit = FakeReddit(redditors={"borrower": redditor})

        comment = self.run_stats_command(reddit)

        self.assertIn("Account Statistics for u/borrower", comment.replies[0])
        self.assertIn("Comments Scanned:** 2", comment.replies[0])
        self.assertIn("Combined Karma:** 33", comment.replies[0])
        self.assertIn("Verified Email:** No", comment.replies[0])

    def test_stats_no_comments_gets_no_comments_reply(self):
        reddit = FakeReddit(redditors={"borrower": FakeRedditor(comments=[])})

        comment = self.run_stats_command(reddit)

        self.assertEqual(comment.replies[0], "No comments found for u/borrower.")

    def test_stats_without_username_gets_no_reply(self):
        reddit = FakeReddit(redditors={})

        comment = self.run_stats_command(reddit, body="$stats")

        self.assertEqual(comment.replies, [])


if __name__ == "__main__":
    unittest.main()
