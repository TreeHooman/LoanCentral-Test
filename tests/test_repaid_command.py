import importlib
import sys
import unittest
from decimal import Decimal
from unittest.mock import patch

from tests.support.fakes import FakeComment, FakeDb, fake_utils_module, loan_record


class RepaidCommandTests(unittest.TestCase):
    def run_repaid_command(self, fake_db, body, author_name="borrower"):
        with patch.dict(sys.modules, {"utils": fake_utils_module(fake_db)}):
            repaid_command = importlib.import_module("commands.repaid_command")
            comment = FakeComment(body=body, author_name=author_name)
            repaid_command.process_repaid_command(comment)
            return comment

    def test_borrower_can_record_partial_repayment(self):
        fake_db = FakeDb(
            loans=[loan_record(db_id=21, amount="100.00")],
            users={"borrower": {"amount_repaid": Decimal("0")}},
        )

        comment = self.run_repaid_command(fake_db, "$repaid 21 40 USD")

        self.assertEqual(fake_db.loans[0]["amount_repaid"], Decimal("40"))
        self.assertEqual(fake_db.loans[0]["status"], "partially_repaid")
        self.assertEqual(fake_db.users["borrower"]["amount_repaid"], Decimal("40"))
        self.assertIn("still need to repay 60.00 USD", comment.replies[0])

    def test_borrower_can_record_repayment_by_public_loan_id(self):
        fake_db = FakeDb(
            loans=[loan_record(db_id=21, public_id="1700000021", amount="100.00")],
            users={"borrower": {"amount_repaid": Decimal("0")}},
        )

        comment = self.run_repaid_command(fake_db, "$repaid 1700000021 100 USD")

        self.assertEqual(fake_db.loans[0]["amount_repaid"], Decimal("100"))
        self.assertEqual(fake_db.loans[0]["status"], "repaid")
        self.assertEqual(fake_db.users["borrower"]["amount_repaid"], Decimal("100"))
        self.assertIn("fully repaid", comment.replies[0])

    def test_wrong_borrower_cannot_record_repayment(self):
        fake_db = FakeDb(loans=[loan_record(db_id=21, borrower="borrower")])

        comment = self.run_repaid_command(fake_db, "$repaid 21 40 USD", author_name="other_user")

        self.assertEqual(fake_db.loans[0]["amount_repaid"], Decimal("0.00"))
        self.assertIn("where you are the borrower", comment.replies[0])

    def test_borrower_cannot_record_more_than_remaining_balance(self):
        fake_db = FakeDb(
            loans=[loan_record(db_id=21, amount="100.00", amount_repaid="80.00")],
            users={"borrower": {"amount_repaid": Decimal("80")}},
        )

        comment = self.run_repaid_command(fake_db, "$repaid 21 25 USD")

        self.assertEqual(fake_db.loans[0]["amount_repaid"], Decimal("80.00"))
        self.assertEqual(fake_db.loans[0]["status"], "confirmed")
        self.assertEqual(fake_db.users["borrower"]["amount_repaid"], Decimal("80"))
        self.assertIn("exceeds the remaining balance", comment.replies[0])

    def test_partial_repayment_on_unpaid_loan_reduces_unpaid_amount_only(self):
        fake_db = FakeDb(
            loans=[loan_record(db_id=21, amount="100.00", amount_repaid="25.00", status="unpaid")],
            users={"borrower": {"amount_repaid": Decimal("25"), "unpaid_loans": 1, "unpaid_amount": Decimal("75")}},
        )

        comment = self.run_repaid_command(fake_db, "$repaid 21 30 USD")

        self.assertEqual(fake_db.loans[0]["amount_repaid"], Decimal("55.00"))
        self.assertEqual(fake_db.loans[0]["status"], "partially_repaid")
        self.assertEqual(fake_db.users["borrower"]["amount_repaid"], Decimal("55"))
        self.assertEqual(fake_db.users["borrower"]["unpaid_loans"], 1)
        self.assertEqual(fake_db.users["borrower"]["unpaid_amount"], Decimal("45"))
        self.assertIn("still need to repay 45.00 USD", comment.replies[0])

    def test_full_repayment_on_unpaid_loan_clears_one_unpaid_count_and_remaining_amount(self):
        fake_db = FakeDb(
            loans=[loan_record(db_id=21, amount="100.00", amount_repaid="25.00", status="unpaid")],
            users={"borrower": {"amount_repaid": Decimal("25"), "unpaid_loans": 2, "unpaid_amount": Decimal("125")}},
        )

        comment = self.run_repaid_command(fake_db, "$repaid 21 75 USD")

        self.assertEqual(fake_db.loans[0]["amount_repaid"], Decimal("100.00"))
        self.assertEqual(fake_db.loans[0]["status"], "repaid")
        self.assertEqual(fake_db.users["borrower"]["amount_repaid"], Decimal("100"))
        self.assertEqual(fake_db.users["borrower"]["unpaid_loans"], 1)
        self.assertEqual(fake_db.users["borrower"]["unpaid_amount"], Decimal("50"))
        self.assertIn("fully repaid", comment.replies[0])

    def test_zero_repayment_is_rejected(self):
        fake_db = FakeDb(loans=[loan_record(db_id=21)])

        comment = self.run_repaid_command(fake_db, "$repaid 21 0 USD")

        self.assertEqual(fake_db.loans[0]["amount_repaid"], Decimal("0.00"))
        self.assertIn("greater than zero", comment.replies[0])

    def test_refunded_loan_cannot_be_repaid(self):
        fake_db = FakeDb(loans=[loan_record(db_id=21, status="refunded")])

        comment = self.run_repaid_command(fake_db, "$repaid 21 25 USD")

        self.assertEqual(fake_db.loans[0]["amount_repaid"], Decimal("0.00"))
        self.assertIn("has been refunded", comment.replies[0])


if __name__ == "__main__":
    unittest.main()
