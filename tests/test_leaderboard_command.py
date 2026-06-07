"""
Tests for the $leaderboard command.
$leaderboard — posts top 5 lenders and top 5 borrowers by repayment rate.
"""
import importlib
import sys
import unittest
from decimal import Decimal
from unittest.mock import patch

from tests.support.fakes import FakeComment, FakeDb, fake_utils_module


def run_leaderboard_command(fake_db, body, author_name="user"):
    comment = FakeComment(body=body, author_name=author_name)
    with patch.dict(sys.modules, {"utils": fake_utils_module(fake_db)}):
        leaderboard_cmd = importlib.import_module("commands.leaderboard_command")
        importlib.reload(leaderboard_cmd)
        leaderboard_cmd.process_leaderboard_command(comment)
    return comment


class LeaderboardCommandTests(unittest.TestCase):
    def test_leaderboard_shows_top_lenders(self):
        fake_db = FakeDb(
            users={
                "alice": {
                    "loans_as_lender": 5,
                    "amount_lent": Decimal("500.00"),
                    "loans_as_borrower": 0,
                    "amount_borrowed": Decimal("0"),
                    "amount_repaid": Decimal("0"),
                    "unpaid_loans": 0,
                    "unpaid_amount": Decimal("0"),
                },
                "bob": {
                    "loans_as_lender": 3,
                    "amount_lent": Decimal("300.00"),
                    "loans_as_borrower": 0,
                    "amount_borrowed": Decimal("0"),
                    "amount_repaid": Decimal("0"),
                    "unpaid_loans": 0,
                    "unpaid_amount": Decimal("0"),
                },
            }
        )
        comment = run_leaderboard_command(fake_db, "$leaderboard")
        self.assertEqual(len(comment.replies), 1)
        reply = comment.replies[0]
        self.assertIn("Top Lenders", reply)
        self.assertIn("alice", reply)
        self.assertIn("bob", reply)

    def test_leaderboard_no_data(self):
        fake_db = FakeDb()
        comment = run_leaderboard_command(fake_db, "$leaderboard")
        self.assertEqual(len(comment.replies), 1)
        reply = comment.replies[0]
        self.assertIn("No data yet", reply)

    def test_no_trigger(self):
        fake_db = FakeDb()
        comment = run_leaderboard_command(fake_db, "just a regular comment")
        self.assertEqual(comment.replies, [])

    def test_leaderboard_shows_repayment_rate(self):
        fake_db = FakeDb(
            users={
                "goodborrower": {
                    "loans_as_borrower": 3,
                    "amount_borrowed": Decimal("300.00"),
                    "amount_repaid": Decimal("270.00"),
                    "loans_as_lender": 0,
                    "amount_lent": Decimal("0"),
                    "unpaid_loans": 0,
                    "unpaid_amount": Decimal("0"),
                },
            }
        )
        comment = run_leaderboard_command(fake_db, "$leaderboard")
        self.assertEqual(len(comment.replies), 1)
        reply = comment.replies[0]
        self.assertIn("Top Borrowers by Repayment Rate", reply)
        self.assertIn("goodborrower", reply)
        self.assertIn("90.0%", reply)

    def test_leaderboard_includes_dashboard_link(self):
        fake_db = FakeDb()
        comment = run_leaderboard_command(fake_db, "$leaderboard")
        self.assertEqual(len(comment.replies), 1)
        self.assertIn("LoanCentral Dashboard", comment.replies[0])

    def test_leaderboard_lenders_sorted_by_amount(self):
        fake_db = FakeDb(
            users={
                "smalllender": {
                    "loans_as_lender": 10,
                    "amount_lent": Decimal("50.00"),
                    "loans_as_borrower": 0,
                    "amount_borrowed": Decimal("0"),
                    "amount_repaid": Decimal("0"),
                    "unpaid_loans": 0,
                    "unpaid_amount": Decimal("0"),
                },
                "biglender": {
                    "loans_as_lender": 2,
                    "amount_lent": Decimal("5000.00"),
                    "loans_as_borrower": 0,
                    "amount_borrowed": Decimal("0"),
                    "amount_repaid": Decimal("0"),
                    "unpaid_loans": 0,
                    "unpaid_amount": Decimal("0"),
                },
            }
        )
        comment = run_leaderboard_command(fake_db, "$leaderboard")
        reply = comment.replies[0]
        # biglender should appear before smalllender (sorted by amount_lent desc)
        self.assertLess(reply.index("biglender"), reply.index("smalllender"))

    def test_leaderboard_borrower_below_min_loans_excluded(self):
        fake_db = FakeDb(
            users={
                "oneloan": {
                    "loans_as_borrower": 1,
                    "amount_borrowed": Decimal("100.00"),
                    "amount_repaid": Decimal("100.00"),
                    "loans_as_lender": 0,
                    "amount_lent": Decimal("0"),
                    "unpaid_loans": 0,
                    "unpaid_amount": Decimal("0"),
                },
            }
        )
        comment = run_leaderboard_command(fake_db, "$leaderboard")
        reply = comment.replies[0]
        # oneloan has only 1 loan, below the minimum of 2 — should not appear
        self.assertNotIn("oneloan", reply)
        self.assertIn("No data yet", reply)


if __name__ == "__main__":
    unittest.main()
