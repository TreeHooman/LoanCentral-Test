"""Tests for the $forgive command — lender waives a loan."""
import os
import sys
import unittest
from unittest.mock import patch
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.support.fakes import FakeComment, FakeDb, loan_record


def _patch_db(fake):
    return patch("services._get_db", side_effect=lambda: fake.connection())


class ForgiveCommandTests(unittest.TestCase):
    def setUp(self):
        self.loan = loan_record(
            db_id=10, public_id="LOAN010",
            lender="lender1", borrower="borrower1",
            amount="100.00", amount_repaid="20.00",
            status="confirmed",
        )
        self.fake_db = FakeDb(loans=[self.loan])

    def test_forgive_marks_loan_refunded(self):
        comment = FakeComment("$forgive LOAN010", author_name="lender1")
        with _patch_db(self.fake_db):
            from commands.forgive_command import process_forgive_command
            process_forgive_command(comment)
        self.assertEqual(self.fake_db.loans[0]["status"], "refunded")
        self.assertIn("waived", comment.replies[0].lower())

    def test_forgive_reply_mentions_borrower(self):
        comment = FakeComment("$forgive LOAN010", author_name="lender1")
        with _patch_db(self.fake_db):
            from commands.forgive_command import process_forgive_command
            process_forgive_command(comment)
        self.assertIn("borrower1", comment.replies[0])

    def test_non_lender_cannot_forgive(self):
        comment = FakeComment("$forgive LOAN010", author_name="otherperson")
        with _patch_db(self.fake_db):
            from commands.forgive_command import process_forgive_command
            process_forgive_command(comment)
        self.assertIn("could not find", comment.replies[0].lower())
        self.assertEqual(self.fake_db.loans[0]["status"], "confirmed")

    def test_already_repaid_loan_cannot_be_forgiven(self):
        repaid_loan = loan_record(
            db_id=11, public_id="LOAN011",
            lender="lender1", borrower="borrower1",
            amount="50.00", amount_repaid="50.00",
            status="repaid",
        )
        db = FakeDb(loans=[repaid_loan])
        comment = FakeComment("$forgive LOAN011", author_name="lender1")
        with patch("services._get_db", side_effect=lambda: db.connection()):
            from commands.forgive_command import process_forgive_command
            process_forgive_command(comment)
        self.assertIn("already", comment.replies[0].lower())

    def test_no_match_no_reply(self):
        comment = FakeComment("just talking", author_name="lender1")
        with _patch_db(self.fake_db):
            from commands.forgive_command import process_forgive_command
            process_forgive_command(comment)
        self.assertEqual(len(comment.replies), 0)

    def test_forgive_unpaid_loan_clears_unpaid_record(self):
        unpaid_loan = loan_record(
            db_id=12, public_id="LOAN012",
            lender="lender1", borrower="borrower1",
            amount="100.00", amount_repaid="0.00",
            status="unpaid",
        )
        db = FakeDb(
            loans=[unpaid_loan],
            users={"borrower1": {"unpaid_loans": 2, "unpaid_amount": Decimal("150")}},
        )
        comment = FakeComment("$forgive LOAN012", author_name="lender1")
        with patch("services._get_db", side_effect=lambda: db.connection()):
            from commands.forgive_command import process_forgive_command
            process_forgive_command(comment)
        self.assertEqual(db.users["borrower1"]["unpaid_loans"], 1)

    def test_banned_lender_cannot_forgive(self):
        db = FakeDb(
            loans=[self.loan],
            bans={"lender1": {"username": "lender1", "reason": "banned", "banned_by": "mod"}},
        )
        comment = FakeComment("$forgive LOAN010", author_name="lender1")
        with patch("services._get_db", side_effect=lambda: db.connection()):
            from commands.forgive_command import process_forgive_command
            process_forgive_command(comment)
        self.assertIn("suspended", comment.replies[0].lower())
        self.assertEqual(db.loans[0]["status"], "confirmed")

    def test_discord_notify_on_forgiveness(self):
        comment = FakeComment("$forgive LOAN010", author_name="lender1")
        with _patch_db(self.fake_db), \
             patch("notifications.notify_discord") as mock_discord:
            from commands.forgive_command import process_forgive_command
            process_forgive_command(comment)
        mock_discord.assert_called_once()
        self.assertIn("forgiven", mock_discord.call_args[0][0].lower())


if __name__ == "__main__":
    unittest.main()
