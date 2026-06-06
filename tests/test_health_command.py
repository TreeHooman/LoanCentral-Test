import importlib
import sys
import unittest
from decimal import Decimal
from unittest.mock import patch

from tests.support.fakes import FakeComment, FakeDb, fake_utils_module


class HealthCommandTests(unittest.TestCase):
    def run_health_command(self, fake_db, body="$health u/borrower"):
        with patch.dict(sys.modules, {"utils": fake_utils_module(fake_db)}):
            health_command = importlib.import_module("commands.health_command")
            comment = FakeComment(body=body, author_name="lender")
            health_command.process_health_command(comment)
            return comment

    def test_no_history_user_gets_no_history_report(self):
        fake_db = FakeDb(users={})

        comment = self.run_health_command(fake_db)

        self.assertIn("no loan history", comment.replies[0])

    def test_health_report_uses_user_totals(self):
        fake_db = FakeDb(
            users={
                "borrower": {
                    "loans_as_borrower": 4,
                    "amount_borrowed": Decimal("200"),
                    "amount_repaid": Decimal("150"),
                    "unpaid_loans": 1,
                }
            }
        )

        comment = self.run_health_command(fake_db)

        self.assertIn("Health Report for u/borrower", comment.replies[0])
        self.assertIn("3/4 loans completed", comment.replies[0])
        self.assertIn("$150.00/$200.00 repaid", comment.replies[0])


if __name__ == "__main__":
    unittest.main()

