"""
Tests for the $apply command — loan application submission and cancellation.
"""
import importlib
import sys
import unittest
from decimal import Decimal
from unittest.mock import patch

import services
from tests.support.fakes import FakeComment, FakeDb, FakeSubreddit, FakeSubmission, fake_utils_module


def run_apply_command(fake_db, body, author_name="borrower"):
    subreddit = FakeSubreddit()
    submission = FakeSubmission(author_name=author_name, subreddit=subreddit)
    comment = FakeComment(body=body, author_name=author_name, submission=submission, subreddit=subreddit)
    with patch.dict(sys.modules, {"utils": fake_utils_module(fake_db)}):
        with patch("notifications.notify_discord"):
            apply_cmd = importlib.import_module("commands.apply_command")
            importlib.reload(apply_cmd)
            apply_cmd.process_apply_command(comment)
    return comment


class ApplyCommandTests(unittest.TestCase):
    def test_borrower_can_submit_application(self):
        fake_db = FakeDb()
        comment = run_apply_command(fake_db, "$apply 100 USD need help with rent")
        self.assertEqual(len(comment.replies), 1)
        self.assertIn("Loan application submitted", comment.replies[0])

    def test_reply_contains_application_id(self):
        fake_db = FakeDb()
        comment = run_apply_command(fake_db, "$apply 50 USD")
        self.assertIn("#1", comment.replies[0])

    def test_reply_contains_amount(self):
        fake_db = FakeDb()
        comment = run_apply_command(fake_db, "$apply 200 EUR")
        self.assertIn("200.00", comment.replies[0])
        self.assertIn("EUR", comment.replies[0])

    def test_zero_amount_rejected(self):
        fake_db = FakeDb()
        comment = run_apply_command(fake_db, "$apply 0 USD")
        self.assertIn("Error", comment.replies[0])
        self.assertIn("greater than zero", comment.replies[0])

    def test_no_match_gets_no_reply(self):
        fake_db = FakeDb()
        comment = run_apply_command(fake_db, "$apply no numbers here")
        self.assertEqual(len(comment.replies), 0)

    def test_reply_includes_cancel_hint(self):
        fake_db = FakeDb()
        comment = run_apply_command(fake_db, "$apply 75 USD")
        self.assertIn("$apply cancel", comment.replies[0])

    def test_cancel_command_on_nonexistent_id_replies_error(self):
        fake_db = FakeDb()
        comment = run_apply_command(fake_db, "$apply cancel #999")
        self.assertEqual(len(comment.replies), 1)
        self.assertIn("No open application", comment.replies[0])

    def test_discord_notify_called_on_success(self):
        fake_db = FakeDb()
        subreddit = FakeSubreddit()
        submission = FakeSubmission(author_name="borrower", subreddit=subreddit)
        comment = FakeComment(body="$apply 100 USD", author_name="borrower",
                              submission=submission, subreddit=subreddit)
        discord_calls = []
        with patch.dict(sys.modules, {"utils": fake_utils_module(fake_db)}):
            with patch("notifications.notify_discord", side_effect=lambda m: discord_calls.append(m)):
                apply_cmd = importlib.import_module("commands.apply_command")
                importlib.reload(apply_cmd)
                apply_cmd.process_apply_command(comment)
        self.assertTrue(len(discord_calls) > 0)
        self.assertIn("Loan Request", discord_calls[0])


if __name__ == "__main__":
    unittest.main()
