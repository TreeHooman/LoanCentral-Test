import importlib
import unittest
from decimal import Decimal
from unittest.mock import patch

from tests.support.fakes import FakeComment


class LogiCommandTests(unittest.TestCase):
    def run_command(self, body, stats=None, error=None):
        comment = FakeComment(body=body, author_name="viewer")
        logi_command = importlib.import_module("commands.logi_command")
        importlib.reload(logi_command)
        with patch("services.get_lender_stats", return_value=(stats, error)):
            logi_command.process_logi_command(comment)
        return comment

    def test_logi_renders_lender_stats(self):
        comment = self.run_command("$logi u/ExampleLender", {
            "total_lent": Decimal("4250.00"),
            "total_recovered": Decimal("3640.00"),
            "total_loans": 28,
            "active_loans": 6,
            "repaid_loans": 20,
            "unpaid_loans": 2,
        })

        self.assertEqual(len(comment.replies), 1)
        reply = comment.replies[0]
        self.assertIn("Lender Snapshot: u/examplelender", reply)
        self.assertIn("| Amount Lent | $4,250.00 |", reply)
        self.assertIn("| Received Back | $3,640.00 |", reply)
        self.assertIn("| Total Loans | 28 |", reply)
        self.assertIn("| Ongoing Loans | 6 |", reply)
        self.assertIn("| Paid Loans | 20 |", reply)
        self.assertIn("| Unpaid Loans | 2 |", reply)

    def test_logi_accepts_username_without_u_prefix(self):
        comment = self.run_command("$logi ExampleLender", {
            "total_lent": 0,
            "total_recovered": 0,
            "total_loans": 0,
            "active_loans": 0,
            "repaid_loans": 0,
            "unpaid_loans": 0,
        })

        self.assertIn("u/examplelender", comment.replies[0])

    def test_slash_logi_does_not_trigger(self):
        comment = self.run_command("/logi u/ExampleLender", {
            "total_lent": 100,
        })

        self.assertEqual(comment.replies, [])

    def test_logi_reports_service_error(self):
        comment = self.run_command("$logi u/ExampleLender", error="Database connection failed.")

        self.assertEqual(len(comment.replies), 1)
        self.assertIn("Error: Database connection failed.", comment.replies[0])


if __name__ == "__main__":
    unittest.main()
