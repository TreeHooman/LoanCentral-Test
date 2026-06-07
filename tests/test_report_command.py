"""
Tests for the $report command — user reports and Discord notifications.
"""
import importlib
import sys
import os
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.support.fakes import FakeComment, FakeDb, FakeSubreddit, FakeSubmission, FakeReddit, fake_utils_module


def run_report_command(fake_db, body, author_name="reporter", fake_reddit=None):
    subreddit = FakeSubreddit()
    submission = FakeSubmission(author_name=author_name, subreddit=subreddit)
    comment = FakeComment(body=body, author_name=author_name, submission=submission, subreddit=subreddit)
    reddit = fake_reddit or FakeReddit()
    with patch.dict(sys.modules, {"utils": fake_utils_module(fake_db, reddit=reddit)}):
        with patch("notifications.notify_discord") as mock_discord:
            with patch.dict(os.environ, {"SUBREDDITS": "LoanCentralTest"}):
                report_cmd = importlib.import_module("commands.report_command")
                importlib.reload(report_cmd)
                report_cmd.process_report_command(comment)
    return comment


class ReportCommandTests(unittest.TestCase):
    def test_report_sends_modmail_reply(self):
        fake_db = FakeDb()
        comment = run_report_command(fake_db, "$report u/baduser scammer")
        self.assertEqual(len(comment.replies), 1)
        self.assertIn("Report submitted", comment.replies[0])

    def test_report_mentions_reported_user(self):
        fake_db = FakeDb()
        comment = run_report_command(fake_db, "$report u/baduser")
        self.assertIn("baduser", comment.replies[0])

    def test_cannot_report_yourself(self):
        fake_db = FakeDb()
        comment = run_report_command(fake_db, "$report u/reporter", author_name="reporter")
        self.assertIn("cannot report yourself", comment.replies[0])

    def test_no_match_no_reply(self):
        fake_db = FakeDb()
        comment = run_report_command(fake_db, "just a normal comment")
        self.assertEqual(len(comment.replies), 0)

    def test_discord_notify_called_on_report(self):
        fake_db = FakeDb()
        subreddit = FakeSubreddit()
        submission = FakeSubmission(author_name="reporter", subreddit=subreddit)
        comment = FakeComment(body="$report u/baduser scammed me",
                              author_name="reporter", submission=submission, subreddit=subreddit)
        discord_calls = []
        with patch.dict(sys.modules, {"utils": fake_utils_module(fake_db, reddit=FakeReddit())}):
            with patch("notifications.notify_discord", side_effect=lambda m: discord_calls.append(m)):
                with patch.dict(os.environ, {"SUBREDDITS": "LoanCentralTest"}):
                    report_cmd = importlib.import_module("commands.report_command")
                    importlib.reload(report_cmd)
                    report_cmd.process_report_command(comment)
        self.assertTrue(len(discord_calls) > 0)
        self.assertIn("Report Filed", discord_calls[0])
        self.assertIn("baduser", discord_calls[0])

    def test_case_insensitive_username(self):
        fake_db = FakeDb()
        comment = run_report_command(fake_db, "$report U/BadUser some reason")
        self.assertEqual(len(comment.replies), 1)
        self.assertIn("Report submitted", comment.replies[0])


if __name__ == "__main__":
    unittest.main()
