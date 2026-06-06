import importlib
import sys
import unittest
from decimal import Decimal
from unittest.mock import patch

from tests.support.fakes import FakeComment, FakeDb, FakeReddit, FakeSubmission, fake_utils_module, loan_record


class RefundCommandTests(unittest.TestCase):
    def run_refund_command(self, fake_db, body="refunded", author_name="lender", parent_author="LoanCentralTestBot"):
        parent = FakeComment(
            body="Confirmed: u/borrower has confirmed receiving 100.00 USD from u/lender.",
            author_name=parent_author,
        )
        subreddit = FakeReddit().subreddit("LoanCentralTest")
        submission = FakeSubmission(author_name="borrower", subreddit=subreddit)
        comment = FakeComment(
            body=body,
            author_name=author_name,
            parent_comment=parent,
            submission=submission,
            subreddit=subreddit,
        )
        fake_reddit = FakeReddit()
        fake_reddit.subreddits["LoanCentralTest"] = subreddit

        with patch.dict(sys.modules, {"utils": fake_utils_module(fake_db, reddit=fake_reddit)}):
            with patch.dict("os.environ", {"REDDIT_USERNAME": "LoanCentralTestBot"}):
                refund_command = importlib.import_module("commands.refund_command")
                refund_command.process_refund_command(comment)

        return comment, subreddit

    def test_lender_can_refund_matching_loan(self):
        fake_db = FakeDb(
            loans=[loan_record(db_id=41, amount="100.00")],
            users={
                "lender": {"loans_as_lender": 1, "amount_lent": Decimal("100")},
                "borrower": {"loans_as_borrower": 1, "amount_borrowed": Decimal("100")},
            },
        )

        comment, subreddit = self.run_refund_command(fake_db)

        self.assertEqual(fake_db.loans[0]["status"], "refunded")
        self.assertEqual(fake_db.users["lender"]["loans_as_lender"], 0)
        self.assertEqual(fake_db.users["lender"]["amount_lent"], Decimal("0"))
        self.assertEqual(fake_db.users["borrower"]["loans_as_borrower"], 0)
        self.assertEqual(fake_db.users["borrower"]["amount_borrowed"], Decimal("0"))
        self.assertIn("Loan marked as refunded", comment.replies[0])
        self.assertEqual(len(subreddit.messages), 1)

    def test_only_lender_can_refund(self):
        fake_db = FakeDb(loans=[loan_record(db_id=41, amount="100.00")])

        comment, subreddit = self.run_refund_command(fake_db, author_name="borrower")

        self.assertEqual(fake_db.loans[0]["status"], "confirmed")
        self.assertIn("Only the lender", comment.replies[0])
        self.assertEqual(subreddit.messages, [])

    def test_already_refunded_loan_does_not_reverse_stats_again(self):
        fake_db = FakeDb(
            loans=[loan_record(db_id=41, amount="100.00", status="refunded")],
            users={
                "lender": {"loans_as_lender": 0, "amount_lent": Decimal("0")},
                "borrower": {"loans_as_borrower": 0, "amount_borrowed": Decimal("0")},
            },
        )

        comment, subreddit = self.run_refund_command(fake_db)

        self.assertEqual(fake_db.loans[0]["status"], "refunded")
        self.assertEqual(fake_db.users["lender"]["loans_as_lender"], 0)
        self.assertEqual(fake_db.users["borrower"]["loans_as_borrower"], 0)
        self.assertIn("already been marked as refunded", comment.replies[0])
        self.assertEqual(subreddit.messages, [])


if __name__ == "__main__":
    unittest.main()
