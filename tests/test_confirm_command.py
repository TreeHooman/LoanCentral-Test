import importlib
import sys
import unittest
from decimal import Decimal
from unittest.mock import patch

from tests.support.fakes import FakeComment, FakeDb, FakeSubmission, fake_utils_module, loan_record


class ConfirmCommandTests(unittest.TestCase):
    def run_confirm_command(
        self,
        fake_db,
        body,
        author_name="borrower",
        post_author_name="borrower",
        permalink="/r/LoanCentralTest/comments/abc/test/",
    ):
        submission = FakeSubmission(author_name=post_author_name, permalink=permalink)
        comment = FakeComment(body=body, author_name=author_name, submission=submission)

        import services
        with patch.dict(sys.modules, {"utils": fake_utils_module(fake_db)}):
            confirm_command = importlib.import_module("commands.confirm_command")
            with patch.object(services, "_generate_loan_id", return_value="public-123"):
                confirm_command.process_confirm_command(comment)

        return comment

    def test_original_requester_can_confirm_loan(self):
        fake_db = FakeDb()

        comment = self.run_confirm_command(fake_db, "$confirm /u/lender 100 USD")

        self.assertEqual(len(fake_db.loans), 1)
        self.assertEqual(fake_db.loans[0]["loan_id"], "public-123")
        self.assertEqual(fake_db.loans[0]["lender"], "lender")
        self.assertEqual(fake_db.loans[0]["borrower"], "borrower")
        self.assertEqual(fake_db.loans[0]["amount"], Decimal("100"))
        self.assertEqual(fake_db.loans[0]["currency"], "USD")
        self.assertEqual(fake_db.loans[0]["status"], "confirmed")
        self.assertEqual(fake_db.users["lender"]["loans_as_lender"], 1)
        self.assertEqual(fake_db.users["lender"]["amount_lent"], Decimal("100"))
        self.assertEqual(fake_db.users["borrower"]["loans_as_borrower"], 1)
        self.assertEqual(fake_db.users["borrower"]["amount_borrowed"], Decimal("100"))
        self.assertIn("$paid_with_id 1 100.00 USD", comment.replies[0])

    def test_original_requester_can_confirm_with_u_slash_format(self):
        fake_db = FakeDb()

        comment = self.run_confirm_command(fake_db, "$confirm u/lender 50 CAD")

        self.assertEqual(len(fake_db.loans), 1)
        self.assertEqual(fake_db.loans[0]["lender"], "lender")
        self.assertEqual(fake_db.loans[0]["amount"], Decimal("50"))
        self.assertEqual(fake_db.loans[0]["currency"], "CAD")
        self.assertIn("Confirmed: u/borrower", comment.replies[0])

    def test_non_original_requester_cannot_confirm(self):
        fake_db = FakeDb()

        comment = self.run_confirm_command(
            fake_db,
            "$confirm /u/lender 100 USD",
            author_name="not_borrower",
            post_author_name="borrower",
        )

        self.assertEqual(fake_db.loans, [])
        self.assertIn("Only the original requester", comment.replies[0])

    def test_exact_duplicate_confirmation_is_blocked(self):
        fake_db = FakeDb(
            loans=[
                loan_record(
                    db_id=7,
                    lender="lender",
                    borrower="borrower",
                    amount="100.00",
                    currency="USD",
                    status="confirmed",
                    original_thread="https://www.reddit.com/r/LoanCentralTest/comments/abc/test/",
                )
            ]
        )

        comment = self.run_confirm_command(fake_db, "$confirm /u/lender 100 USD")

        self.assertEqual(len(fake_db.loans), 1)
        self.assertIn("already confirmed this loan", comment.replies[0])

    def test_same_lender_borrower_can_confirm_different_thread(self):
        fake_db = FakeDb(
            loans=[
                loan_record(
                    db_id=7,
                    lender="lender",
                    borrower="borrower",
                    amount="100.00",
                    currency="USD",
                    status="confirmed",
                    original_thread="https://www.reddit.com/r/LoanCentralTest/comments/abc/test/",
                )
            ]
        )

        comment = self.run_confirm_command(
            fake_db,
            "$confirm /u/lender 100 USD",
            permalink="/r/LoanCentralTest/comments/def/new_test/",
        )

        self.assertEqual(len(fake_db.loans), 2)
        self.assertIn("Confirmed: u/borrower", comment.replies[0])

    def test_zero_confirm_amount_is_rejected(self):
        fake_db = FakeDb()

        comment = self.run_confirm_command(fake_db, "$confirm /u/lender 0 USD")

        self.assertEqual(fake_db.loans, [])
        self.assertIn("greater than zero", comment.replies[0])


if __name__ == "__main__":
    unittest.main()
