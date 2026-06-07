"""Tests for the $dispute command."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.support.fakes import FakeComment, FakeDb, loan_record


def _patch_db(fake):
    return patch("services._get_db", side_effect=lambda: fake.connection())


def _unpaid_loan(db_id=1, borrower="borrower1", lender="lender1"):
    return loan_record(
        db_id=db_id, public_id="LOAN001",
        borrower=borrower, lender=lender,
        amount="100.00", status="unpaid",
    )


class DisputeCommandTests(unittest.TestCase):
    def setUp(self):
        loan = _unpaid_loan()
        self.fake_db = FakeDb(loans=[loan])

    def test_dispute_creates_dispute_id(self):
        comment = FakeComment("$dispute LOAN001 I repaid this", author_name="borrower1")
        with _patch_db(self.fake_db):
            from commands.dispute_command import process_dispute_command
            process_dispute_command(comment)
        self.assertEqual(len(comment.replies), 1)
        self.assertIn("#1", comment.replies[0])

    def test_dispute_reply_mentions_loan_id(self):
        comment = FakeComment("$dispute LOAN001 paid via venmo", author_name="borrower1")
        with _patch_db(self.fake_db):
            from commands.dispute_command import process_dispute_command
            process_dispute_command(comment)
        self.assertIn("LOAN001", comment.replies[0])

    def test_dispute_on_nonexistent_loan(self):
        comment = FakeComment("$dispute 9999999 fake id", author_name="borrower1")
        with _patch_db(self.fake_db):
            from commands.dispute_command import process_dispute_command
            process_dispute_command(comment)
        self.assertIn("not found", comment.replies[0].lower())

    def test_dispute_wrong_borrower_rejected(self):
        comment = FakeComment("$dispute LOAN001 not my loan", author_name="otherperson")
        with _patch_db(self.fake_db):
            from commands.dispute_command import process_dispute_command
            process_dispute_command(comment)
        self.assertIn("own loans", comment.replies[0].lower())

    def test_dispute_active_loan_rejected(self):
        active_loan = loan_record(
            db_id=2, public_id="LOAN002",
            borrower="borrower1", lender="lender1",
            amount="50.00", status="confirmed",
        )
        db = FakeDb(loans=[active_loan])
        comment = FakeComment("$dispute LOAN002 wrong status", author_name="borrower1")
        with patch("services._get_db", side_effect=lambda: db.connection()):
            from commands.dispute_command import process_dispute_command
            process_dispute_command(comment)
        self.assertIn("unpaid", comment.replies[0].lower())

    def test_no_match_shows_usage(self):
        comment = FakeComment("$dispute", author_name="borrower1")
        with _patch_db(self.fake_db):
            from commands.dispute_command import process_dispute_command
            process_dispute_command(comment)
        self.assertEqual(len(comment.replies), 1)
        self.assertIn("usage", comment.replies[0].lower())

    def test_banned_user_cannot_dispute(self):
        db = FakeDb(
            loans=[_unpaid_loan()],
            bans={"borrower1": {"username": "borrower1", "reason": "test", "banned_by": "mod"}},
        )
        comment = FakeComment("$dispute LOAN001 I paid", author_name="borrower1")
        with patch("services._get_db", side_effect=lambda: db.connection()):
            from commands.dispute_command import process_dispute_command
            process_dispute_command(comment)
        self.assertIn("suspended", comment.replies[0].lower())

    def test_discord_notify_on_success(self):
        comment = FakeComment("$dispute LOAN001 I have proof", author_name="borrower1")
        with _patch_db(self.fake_db), \
             patch("notifications.notify_discord") as mock_discord:
            from commands.dispute_command import process_dispute_command
            process_dispute_command(comment)
        mock_discord.assert_called_once()
        call_arg = mock_discord.call_args[0][0]
        self.assertIn("dispute", call_arg.lower())


if __name__ == "__main__":
    unittest.main()
