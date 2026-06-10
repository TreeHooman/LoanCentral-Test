"""
Tests for $refunded [loan_id] - lender cancels a loan by ID.
"""
import importlib
import sys
import unittest
from decimal import Decimal
from unittest.mock import patch

from tests.support.fakes import FakeComment, FakeDb, FakeReddit, FakeSubmission, FakeSubreddit, fake_utils_module, loan_record


class RefundCommandTests(unittest.TestCase):
    def run_refund_command(self, fake_db, body, author_name="lender", flair_text="Verified Lender"):
        subreddit = FakeSubreddit("LoanCentralTest", flair_text=flair_text)
        submission = FakeSubmission(author_name="borrower", subreddit=subreddit)
        comment = FakeComment(
            body=body,
            author_name=author_name,
            submission=submission,
            subreddit=subreddit,
        )
        fake_reddit = FakeReddit()
        fake_reddit.subreddits["LoanCentralTest"] = subreddit

        with patch.dict(sys.modules, {"utils": fake_utils_module(fake_db, reddit=fake_reddit)}):
            refund_command = importlib.import_module("commands.refund_command")
            importlib.reload(refund_command)
            refund_command.process_refund_command(comment)

        return comment, subreddit

    def test_lender_can_refund_loan_by_id(self):
        fake_db = FakeDb(
            loans=[loan_record(db_id=41, amount="100.00")],
            users={
                "lender": {"loans_as_lender": 1, "amount_lent": Decimal("100")},
                "borrower": {"loans_as_borrower": 1, "amount_borrowed": Decimal("100")},
            },
        )
        comment, subreddit = self.run_refund_command(fake_db, "$refunded 41")

        self.assertEqual(fake_db.loans[0]["status"], "refunded")
        self.assertEqual(fake_db.users["lender"]["loans_as_lender"], 0)
        self.assertEqual(fake_db.users["lender"]["amount_lent"], Decimal("0"))
        self.assertEqual(fake_db.users["borrower"]["loans_as_borrower"], 0)
        self.assertEqual(fake_db.users["borrower"]["amount_borrowed"], Decimal("0"))
        self.assertIn("marked as refunded", comment.replies[0])
        self.assertEqual(len(subreddit.messages), 1)

    def test_wrong_lender_cannot_refund(self):
        fake_db = FakeDb(
            loans=[loan_record(db_id=41, lender="real_lender")],
            verified_lenders=["wrong_lender"],
        )

        comment, subreddit = self.run_refund_command(fake_db, "$refunded 41", author_name="wrong_lender")

        self.assertEqual(fake_db.loans[0]["status"], "confirmed")
        self.assertIn("Could not find a loan", comment.replies[0])
        self.assertEqual(subreddit.messages, [])

    def test_already_refunded_loan_gives_error(self):
        fake_db = FakeDb(
            loans=[loan_record(db_id=41, amount="100.00", status="refunded")],
            users={
                "lender": {"loans_as_lender": 0, "amount_lent": Decimal("0")},
                "borrower": {"loans_as_borrower": 0, "amount_borrowed": Decimal("0")},
            },
        )
        comment, subreddit = self.run_refund_command(fake_db, "$refunded 41")

        self.assertEqual(fake_db.loans[0]["status"], "refunded")
        self.assertEqual(fake_db.users["lender"]["loans_as_lender"], 0)
        self.assertIn("already been marked as refunded", comment.replies[0])
        self.assertEqual(subreddit.messages, [])

    def test_missing_loan_id_gets_no_reply(self):
        fake_db = FakeDb(loans=[loan_record(db_id=41)])
        comment, _ = self.run_refund_command(fake_db, "$refunded")
        self.assertEqual(len(comment.replies), 0)

    def test_repaid_loan_cannot_be_refunded(self):
        fake_db = FakeDb(loans=[loan_record(db_id=41, status="repaid")])
        comment, _ = self.run_refund_command(fake_db, "$refunded 41")
        self.assertIn("already been fully repaid", comment.replies[0])

    def test_verified_lender_without_flair_is_rejected(self):
        fake_db = FakeDb(loans=[loan_record(db_id=41)])
        comment, subreddit = self.run_refund_command(fake_db, "$refunded 41", flair_text="")

        self.assertEqual(fake_db.loans[0]["status"], "confirmed")
        self.assertEqual(subreddit.messages, [])
        self.assertIn("Verified Lender flair", comment.replies[0])


if __name__ == "__main__":
    unittest.main()
