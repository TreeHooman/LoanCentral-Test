"""
Tests for the $mystats command.
$mystats — shows the requesting user's own loan stats and health score.
"""
import importlib
import sys
import unittest
from decimal import Decimal
from unittest.mock import patch

from tests.support.fakes import FakeComment, FakeDb, fake_utils_module, loan_record


def run_mystats_command(fake_db, body, author_name="borrower"):
    comment = FakeComment(body=body, author_name=author_name)
    with patch.dict(sys.modules, {"utils": fake_utils_module(fake_db)}):
        mystats_cmd = importlib.import_module("commands.mystats_command")
        importlib.reload(mystats_cmd)
        mystats_cmd.process_mystats_command(comment)
    return comment


class MyStatsCommandTests(unittest.TestCase):
    def test_mystats_existing_user(self):
        fake_db = FakeDb(
            loans=[loan_record(lender="lender", borrower="borrower", amount="100.00", status="confirmed")],
            users={"borrower": {"loans_as_borrower": 1, "amount_borrowed": Decimal("100.00"),
                                "amount_repaid": Decimal("0"), "unpaid_loans": 0,
                                "unpaid_amount": Decimal("0"), "loans_as_lender": 0,
                                "amount_lent": Decimal("0")}}
        )
        comment = run_mystats_command(fake_db, "$mystats", author_name="borrower")
        self.assertEqual(len(comment.replies), 1)
        reply = comment.replies[0]
        self.assertIn("Health Score", reply)
        self.assertIn("LoanCentral Dashboard", reply)

    def test_mystats_no_history(self):
        fake_db = FakeDb()
        comment = run_mystats_command(fake_db, "$mystats", author_name="borrower")
        self.assertEqual(len(comment.replies), 1)
        self.assertIn("no loan history", comment.replies[0].lower())

    def test_mystats_no_trigger(self):
        fake_db = FakeDb()
        comment = run_mystats_command(fake_db, "just a regular comment", author_name="borrower")
        self.assertEqual(comment.replies, [])

    def test_mystats_with_unpaid(self):
        fake_db = FakeDb(
            loans=[loan_record(lender="lender", borrower="borrower", amount="50.00", status="unpaid")],
            users={"borrower": {"loans_as_borrower": 1, "amount_borrowed": Decimal("50.00"),
                                "amount_repaid": Decimal("0"), "unpaid_loans": 1,
                                "unpaid_amount": Decimal("50.00"), "loans_as_lender": 0,
                                "amount_lent": Decimal("0")}}
        )
        comment = run_mystats_command(fake_db, "$mystats", author_name="borrower")
        self.assertEqual(len(comment.replies), 1)
        reply = comment.replies[0]
        self.assertIn("⚠️", reply)
        self.assertIn("LoanCentral Dashboard", reply)


if __name__ == "__main__":
    unittest.main()
