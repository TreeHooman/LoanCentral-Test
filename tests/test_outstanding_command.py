"""Tests for the $outstanding command."""
import os
import sys
import unittest
from unittest.mock import patch
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.support.fakes import FakeComment, FakeDb, loan_record


def _patch_db(fake):
    return patch("services._get_db", side_effect=lambda: fake.connection())


class OutstandingCommandTests(unittest.TestCase):
    def setUp(self):
        self.active1 = loan_record(
            db_id=1, public_id="L001", lender="lender1", borrower="borrower1",
            amount="100.00", amount_repaid="30.00", status="confirmed",
        )
        self.active2 = loan_record(
            db_id=2, public_id="L002", lender="lender1", borrower="borrower2",
            amount="50.00", amount_repaid="0.00", status="partially_repaid",
        )
        self.repaid = loan_record(
            db_id=3, public_id="L003", lender="lender1", borrower="borrower3",
            amount="25.00", amount_repaid="25.00", status="repaid",
        )
        self.fake_db = FakeDb(loans=[self.active1, self.active2, self.repaid])

    def _run(self, body="$outstanding", author="lender1"):
        comment = FakeComment(body, author_name=author)
        with _patch_db(self.fake_db):
            from commands.outstanding_command import process_outstanding_command
            process_outstanding_command(comment)
        return comment

    def test_shows_active_loans(self):
        comment = self._run()
        self.assertEqual(len(comment.replies), 1)
        self.assertIn("L001", comment.replies[0])
        self.assertIn("L002", comment.replies[0])

    def test_excludes_repaid_loans(self):
        comment = self._run()
        self.assertNotIn("L003", comment.replies[0])

    def test_shows_correct_owed_amount(self):
        comment = self._run()
        # L001: 100 - 30 = 70 owed
        self.assertIn("70.00", comment.replies[0])
        # L002: 50 - 0 = 50 owed
        self.assertIn("50.00", comment.replies[0])

    def test_shows_total_outstanding(self):
        comment = self._run()
        # 70 + 50 = 120 total
        self.assertIn("120.00", comment.replies[0])

    def test_no_active_loans_replies_clear(self):
        db = FakeDb(loans=[self.repaid])
        comment = FakeComment("$outstanding", author_name="lender1")
        with _patch_db(db):
            from commands.outstanding_command import process_outstanding_command
            process_outstanding_command(comment)
        self.assertIn("no outstanding", comment.replies[0].lower())

    def test_different_lender_sees_own_loans(self):
        other = loan_record(
            db_id=4, public_id="L004", lender="otherlender", borrower="borrower4",
            amount="200.00", amount_repaid="0.00", status="confirmed",
        )
        db = FakeDb(loans=[self.active1, other])
        comment = FakeComment("$outstanding", author_name="otherlender")
        with _patch_db(db):
            from commands.outstanding_command import process_outstanding_command
            process_outstanding_command(comment)
        self.assertIn("L004", comment.replies[0])
        self.assertNotIn("L001", comment.replies[0])

    def test_no_trigger_no_reply(self):
        comment = self._run("just chatting")
        self.assertEqual(len(comment.replies), 0)


if __name__ == "__main__":
    unittest.main()
