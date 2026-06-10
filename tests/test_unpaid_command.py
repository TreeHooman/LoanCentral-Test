"""
Tests for $unpaid [loan_id] - lender marks a loan unpaid by ID only.
"""
import importlib
import sys
import unittest
from decimal import Decimal
from unittest.mock import patch

from tests.support.fakes import FakeComment, FakeDb, FakeSubreddit, fake_utils_module, loan_record


class UnpaidCommandTests(unittest.TestCase):
    def run_unpaid_command(self, fake_db, body, author_name="lender", flair_text="Verified Lender"):
        with patch.dict(sys.modules, {"utils": fake_utils_module(fake_db)}):
            unpaid_command = importlib.import_module("commands.unpaid_command")
            importlib.reload(unpaid_command)
            comment = FakeComment(body=body, author_name=author_name, subreddit=FakeSubreddit(flair_text=flair_text))
            unpaid_command.process_unpaid_command(comment)
            return comment

    def test_lender_can_mark_loan_unpaid_by_db_id(self):
        fake_db = FakeDb(
            loans=[loan_record(db_id=31, amount="100.00", amount_repaid="25.00")],
            users={"borrower": {"unpaid_loans": 0, "unpaid_amount": Decimal("0")}},
        )
        comment = self.run_unpaid_command(fake_db, "$unpaid 31")

        self.assertEqual(fake_db.loans[0]["status"], "unpaid")
        self.assertEqual(fake_db.users["borrower"]["unpaid_loans"], 1)
        self.assertEqual(fake_db.users["borrower"]["unpaid_amount"], Decimal("75.00"))
        self.assertIn("has marked their loan", comment.replies[0])

    def test_lender_can_mark_unpaid_by_public_loan_id(self):
        fake_db = FakeDb(
            loans=[loan_record(db_id=31, public_id="1700000031", amount="100.00", amount_repaid="40.00")],
            users={"borrower": {"unpaid_loans": 0, "unpaid_amount": Decimal("0")}},
        )
        comment = self.run_unpaid_command(fake_db, "$unpaid 1700000031")

        self.assertEqual(fake_db.loans[0]["status"], "unpaid")
        self.assertEqual(fake_db.users["borrower"]["unpaid_loans"], 1)
        self.assertEqual(fake_db.users["borrower"]["unpaid_amount"], Decimal("60.00"))
        self.assertIn("has marked their loan", comment.replies[0])

    def test_wrong_lender_cannot_mark_unpaid(self):
        fake_db = FakeDb(
            loans=[loan_record(db_id=31, lender="real_lender")],
            verified_lenders=["wrong_lender"],
        )
        comment = self.run_unpaid_command(fake_db, "$unpaid 31", author_name="wrong_lender")

        self.assertEqual(fake_db.loans[0]["status"], "confirmed")
        self.assertIn("Could not find a loan", comment.replies[0])

    def test_lender_cannot_mark_repaid_loan_unpaid(self):
        fake_db = FakeDb(
            loans=[loan_record(db_id=31, amount="100.00", amount_repaid="100.00", status="repaid")],
            users={"borrower": {"unpaid_loans": 0, "unpaid_amount": Decimal("0")}},
        )
        comment = self.run_unpaid_command(fake_db, "$unpaid 31")

        self.assertEqual(fake_db.loans[0]["status"], "repaid")
        self.assertIn("already been fully repaid", comment.replies[0])

    def test_borrower_not_required_in_command(self):
        """Old syntax needed u/borrower - new syntax just needs loan ID."""
        fake_db = FakeDb(
            loans=[loan_record(db_id=31, amount="100.00", amount_repaid="0.00")],
            users={"borrower": {"unpaid_loans": 0, "unpaid_amount": Decimal("0")}},
        )
        comment = self.run_unpaid_command(fake_db, "$unpaid 31")
        self.assertEqual(fake_db.loans[0]["status"], "unpaid")

    def test_verified_lender_without_flair_is_rejected(self):
        fake_db = FakeDb(loans=[loan_record(db_id=31)])

        comment = self.run_unpaid_command(fake_db, "$unpaid 31", flair_text="")

        self.assertEqual(fake_db.loans[0]["status"], "confirmed")
        self.assertIn("Verified Lender flair", comment.replies[0])


if __name__ == "__main__":
    unittest.main()
