import importlib
import sys
import unittest
from decimal import Decimal
from unittest.mock import patch

from tests.support.fakes import FakeComment, FakeDb, fake_utils_module, loan_record


class UnpaidCommandTests(unittest.TestCase):
    def run_unpaid_command(self, fake_db, body, author_name="lender"):
        with patch.dict(sys.modules, {"utils": fake_utils_module(fake_db)}):
            unpaid_command = importlib.import_module("commands.unpaid_command")
            comment = FakeComment(body=body, author_name=author_name)
            unpaid_command.process_unpaid_command(comment)
            return comment

    def test_lender_can_mark_remaining_balance_unpaid(self):
        fake_db = FakeDb(
            loans=[loan_record(db_id=31, amount="100.00", amount_repaid="25.00")],
            users={"borrower": {"unpaid_loans": 0, "unpaid_amount": Decimal("0")}},
        )

        comment = self.run_unpaid_command(fake_db, "$unpaid 31 u/borrower")

        self.assertEqual(fake_db.loans[0]["status"], "unpaid")
        self.assertEqual(fake_db.users["borrower"]["unpaid_loans"], 1)
        self.assertEqual(fake_db.users["borrower"]["unpaid_amount"], Decimal("75.00"))
        self.assertIn("has marked their loan", comment.replies[0])

    def test_wrong_lender_cannot_mark_unpaid(self):
        fake_db = FakeDb(loans=[loan_record(db_id=31, lender="real_lender")])

        with self.assertLogs("LoanCentral", level="WARNING"):
            comment = self.run_unpaid_command(fake_db, "$unpaid 31 u/borrower", author_name="wrong_lender")

        self.assertEqual(fake_db.loans[0]["status"], "confirmed")
        self.assertIn("Could not find a loan", comment.replies[0])


if __name__ == "__main__":
    unittest.main()
