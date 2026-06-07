"""
Tests for the $check command.
$check u/username — shows a user's public loan stats and health score.
"""
import importlib
import sys
import unittest
from decimal import Decimal
from unittest.mock import patch

import services
from tests.support.fakes import FakeComment, FakeDb, fake_utils_module, loan_record


def run_check_command(fake_db, body, author_name="lender"):
    comment = FakeComment(body=body, author_name=author_name)
    with patch.dict(sys.modules, {"utils": fake_utils_module(fake_db)}):
        check_cmd = importlib.import_module("commands.check_command")
        importlib.reload(check_cmd)
        check_cmd.process_check_command(comment)
    return comment


class CheckCommandTests(unittest.TestCase):
    def test_check_existing_borrower(self):
        fake_db = FakeDb(
            loans=[loan_record(lender="lender", borrower="borrower", amount="100.00", status="confirmed")],
            users={"borrower": {"loans_as_borrower": 1, "amount_borrowed": Decimal("100.00"),
                                "amount_repaid": Decimal("0"), "unpaid_loans": 0,
                                "unpaid_amount": Decimal("0"), "loans_as_lender": 0,
                                "amount_lent": Decimal("0")}}
        )
        comment = run_check_command(fake_db, "$check u/borrower")
        self.assertEqual(len(comment.replies), 1)
        reply = comment.replies[0]
        self.assertIn("borrower", reply)
        self.assertIn("Repayment Score", reply)
        self.assertIn("LoanCentral Dashboard", reply)

    def test_check_with_unpaid_loans(self):
        fake_db = FakeDb(
            loans=[loan_record(lender="lender", borrower="deadbeat", amount="50.00", status="unpaid")],
            users={"deadbeat": {"loans_as_borrower": 1, "amount_borrowed": Decimal("50.00"),
                                "amount_repaid": Decimal("0"), "unpaid_loans": 1,
                                "unpaid_amount": Decimal("50.00"), "loans_as_lender": 0,
                                "amount_lent": Decimal("0")}}
        )
        comment = run_check_command(fake_db, "$check u/deadbeat")
        reply = comment.replies[0]
        self.assertIn("deadbeat", reply)
        self.assertIn("Unpaid", reply)

    def test_check_user_with_no_history(self):
        fake_db = FakeDb()
        comment = run_check_command(fake_db, "$check u/newuser")
        self.assertEqual(len(comment.replies), 1)
        self.assertIn("no loan history", comment.replies[0].lower())

    def test_check_no_match_no_reply(self):
        fake_db = FakeDb()
        comment = run_check_command(fake_db, "just a regular comment")
        self.assertEqual(comment.replies, [])

    def test_check_without_u_prefix(self):
        fake_db = FakeDb(
            users={"borrower": {"loans_as_borrower": 2, "amount_borrowed": Decimal("200.00"),
                                "amount_repaid": Decimal("200.00"), "unpaid_loans": 0,
                                "unpaid_amount": Decimal("0"), "loans_as_lender": 0,
                                "amount_lent": Decimal("0")}}
        )
        comment = run_check_command(fake_db, "$check borrower")
        self.assertEqual(len(comment.replies), 1)
        self.assertIn("borrower", comment.replies[0])

    def test_health_score_perfect_borrower(self):
        fake_db = FakeDb(
            users={"goodpayer": {"loans_as_borrower": 5, "amount_borrowed": Decimal("500.00"),
                                 "amount_repaid": Decimal("500.00"), "unpaid_loans": 0,
                                 "unpaid_amount": Decimal("0"), "loans_as_lender": 0,
                                 "amount_lent": Decimal("0")}}
        )
        comment = run_check_command(fake_db, "$check u/goodpayer")
        reply = comment.replies[0]
        self.assertIn("100/100", reply)
        self.assertIn("Excellent", reply)


class HealthScoreTests(unittest.TestCase):
    def test_perfect_score(self):
        profile = {"loans_as_borrower": 10, "unpaid_loans": 0,
                   "amount_borrowed": 1000, "amount_repaid": 1000}
        score, label = services.calculate_health_score(profile)
        self.assertEqual(score, 100)
        self.assertEqual(label, "Excellent")

    def test_zero_loans_gives_100(self):
        profile = {"loans_as_borrower": 0, "unpaid_loans": 0,
                   "amount_borrowed": 0, "amount_repaid": 0}
        score, label = services.calculate_health_score(profile)
        self.assertEqual(score, 100)
        self.assertEqual(label, "No history")

    def test_all_unpaid_gives_low_score(self):
        profile = {"loans_as_borrower": 5, "unpaid_loans": 5,
                   "amount_borrowed": 500, "amount_repaid": 0}
        score, label = services.calculate_health_score(profile)
        self.assertEqual(score, 0)
        self.assertEqual(label, "Very Poor")

    def test_partial_repayment(self):
        profile = {"loans_as_borrower": 4, "unpaid_loans": 1,
                   "amount_borrowed": 400, "amount_repaid": 300}
        score, label = services.calculate_health_score(profile)
        self.assertGreater(score, 50)
        self.assertLess(score, 100)


if __name__ == "__main__":
    unittest.main()
