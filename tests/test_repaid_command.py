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

    def test_wrong_borrower_cannot_record_repayment(self):
        fake_db = FakeDb(loans=[loan_record(db_id=21, borrower="borrower")])

        comment = self.run_repaid_command(fake_db, "$repaid 21 40 USD", author_name="other_user")

        self.assertEqual(fake_db.loans[0]["amount_repaid"], Decimal("0.00"))
        self.assertIn("where you are the borrower", comment.replies[0])


if __name__ == "__main__":
    unittest.main()

