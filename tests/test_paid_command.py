import importlib
import sys
import unittest
from decimal import Decimal
from unittest.mock import patch

from tests.support.fakes import FakeComment, FakeDb, fake_utils_module, loan_record


class PaidCommandTests(unittest.TestCase):
    def run_paid_command(self, fake_db, body, author_name="lender"):
        with patch.dict(sys.modules, {"utils": fake_utils_module(fake_db)}):
            paid_command = importlib.import_module("commands.paid_command")
            comment = FakeComment(body=body, author_name=author_name)
            paid_command.process_paid_command(comment)
            return comment

    def test_lender_can_record_partial_payment_by_database_id(self):
        fake_db = FakeDb(
            loans=[loan_record(db_id=12, public_id="1700000012")],
            users={"borrower": {"amount_repaid": Decimal("0")}},
        )

        comment = self.run_paid_command(fake_db, "$paid_with_id 12 25 USD")

        self.assertEqual(fake_db.loans[0]["amount_repaid"], Decimal("25"))
        self.assertEqual(fake_db.loans[0]["status"], "partially_repaid")
        self.assertEqual(fake_db.users["borrower"]["amount_repaid"], Decimal("25"))
        self.assertIn("remaining: 75.00 USD", comment.replies[0])

    def test_lender_can_record_full_payment_by_public_loan_id(self):
        fake_db = FakeDb(
            loans=[loan_record(db_id=12, public_id="1700000012", amount_repaid="25.00")],
            users={"borrower": {"amount_repaid": Decimal("25")}},
        )

        comment = self.run_paid_command(fake_db, "$paid_with_id 1700000012 75 USD")

        self.assertEqual(fake_db.loans[0]["amount_repaid"], Decimal("100"))
        self.assertEqual(fake_db.loans[0]["status"], "repaid")
        self.assertEqual(fake_db.users["borrower"]["amount_repaid"], Decimal("100"))
        self.assertIn("remaining: 0.00 USD", comment.replies[0])

    def test_wrong_lender_gets_clear_auth_error(self):
        fake_db = FakeDb(loans=[loan_record(db_id=12, lender="real_lender")])

        with self.assertLogs("LoanCentral", level="WARNING"):
            comment = self.run_paid_command(fake_db, "$paid_with_id 12 25 USD", author_name="wrong_lender")

        self.assertEqual(fake_db.loans[0]["amount_repaid"], Decimal("0.00"))
        self.assertIn("recorded under lender u/real_lender", comment.replies[0])

    def test_missing_loan_gets_clear_not_found_error(self):
        fake_db = FakeDb(loans=[])

        with self.assertLogs("LoanCentral", level="WARNING"):
            comment = self.run_paid_command(fake_db, "$paid_with_id 999 25 USD")

        self.assertIn("Could not find a loan with ID 999", comment.replies[0])

    def test_currency_mismatch_does_not_update_loan(self):
        fake_db = FakeDb(loans=[loan_record(db_id=12, currency="USD")])

        comment = self.run_paid_command(fake_db, "$paid_with_id 12 25 CAD")

        self.assertEqual(fake_db.loans[0]["amount_repaid"], Decimal("0.00"))
        self.assertIn("Currency mismatch", comment.replies[0])

    def test_lender_cannot_record_more_than_remaining_balance(self):
        fake_db = FakeDb(
            loans=[loan_record(db_id=12, amount="100.00", amount_repaid="90.00")],
            users={"borrower": {"amount_repaid": Decimal("90")}},
        )

        comment = self.run_paid_command(fake_db, "$paid_with_id 12 20 USD")

        self.assertEqual(fake_db.loans[0]["amount_repaid"], Decimal("90.00"))
        self.assertEqual(fake_db.loans[0]["status"], "confirmed")
        self.assertEqual(fake_db.users["borrower"]["amount_repaid"], Decimal("90"))
        self.assertIn("exceeds the remaining balance", comment.replies[0])

    def test_partial_payment_on_unpaid_loan_reduces_unpaid_amount_only(self):
        fake_db = FakeDb(
            loans=[loan_record(db_id=12, amount="100.00", amount_repaid="20.00", status="unpaid")],
            users={"borrower": {"amount_repaid": Decimal("20"), "unpaid_loans": 1, "unpaid_amount": Decimal("80")}},
        )

        comment = self.run_paid_command(fake_db, "$paid_with_id 12 30 USD")

        self.assertEqual(fake_db.loans[0]["amount_repaid"], Decimal("50.00"))
        self.assertEqual(fake_db.loans[0]["status"], "partially_repaid")
        self.assertEqual(fake_db.users["borrower"]["amount_repaid"], Decimal("50"))
        self.assertEqual(fake_db.users["borrower"]["unpaid_loans"], 1)
        self.assertEqual(fake_db.users["borrower"]["unpaid_amount"], Decimal("50"))
        self.assertIn("remaining: 50.00 USD", comment.replies[0])

    def test_full_payment_on_unpaid_loan_clears_one_unpaid_count_and_remaining_amount(self):
        fake_db = FakeDb(
            loans=[loan_record(db_id=12, amount="100.00", amount_repaid="20.00", status="unpaid")],
            users={"borrower": {"amount_repaid": Decimal("20"), "unpaid_loans": 2, "unpaid_amount": Decimal("130")}},
        )

        comment = self.run_paid_command(fake_db, "$paid_with_id 12 80 USD")

        self.assertEqual(fake_db.loans[0]["amount_repaid"], Decimal("100.00"))
        self.assertEqual(fake_db.loans[0]["status"], "repaid")
        self.assertEqual(fake_db.users["borrower"]["amount_repaid"], Decimal("100"))
        self.assertEqual(fake_db.users["borrower"]["unpaid_loans"], 1)
        self.assertEqual(fake_db.users["borrower"]["unpaid_amount"], Decimal("50"))
        self.assertIn("remaining: 0.00 USD", comment.replies[0])


if __name__ == "__main__":
    unittest.main()
