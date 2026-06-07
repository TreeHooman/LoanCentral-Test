"""
Tests for the lender-first $loan command.
$loan [amount] [currency] u/[borrower] — creates loan immediately, no confirm needed.
"""
import importlib
import sys
import unittest
from decimal import Decimal
from unittest.mock import patch

import services
from tests.support.fakes import FakeComment, FakeDb, FakeSubreddit, FakeSubmission, fake_utils_module, loan_record


def run_loan_command(fake_db, body, author_name="lender", flair_text="Verified Lender"):
    subreddit = FakeSubreddit(flair_text=flair_text)
    submission = FakeSubmission(author_name="borrower", subreddit=subreddit)
    comment = FakeComment(body=body, author_name=author_name, submission=submission, subreddit=subreddit)
    with patch.dict(sys.modules, {"utils": fake_utils_module(fake_db)}):
        loan_cmd = importlib.import_module("commands.loan_command")
        importlib.reload(loan_cmd)
        with patch.object(services, "_generate_loan_id", return_value="loan-001"):
            loan_cmd.process_loan_command(comment)
    return comment


class LoanCommandTests(unittest.TestCase):
    def test_lender_can_create_loan_immediately(self):
        fake_db = FakeDb()
        comment = run_loan_command(fake_db, "$loan 50 USD u/borrower")

        self.assertEqual(len(fake_db.loans), 1)
        loan = fake_db.loans[0]
        self.assertEqual(loan["lender"], "lender")
        self.assertEqual(loan["borrower"], "borrower")
        self.assertEqual(loan["amount"], Decimal("50"))
        self.assertEqual(loan["currency"], "USD")
        self.assertEqual(loan["status"], "confirmed")
        self.assertIn("Loan recorded", comment.replies[0])

    def test_reply_contains_loan_id(self):
        fake_db = FakeDb()
        comment = run_loan_command(fake_db, "$loan 100 USD u/borrower")
        self.assertIn("loan-001", comment.replies[0])

    def test_reply_contains_lender_commands(self):
        fake_db = FakeDb()
        comment = run_loan_command(fake_db, "$loan 100 USD u/borrower")
        self.assertIn("$paid_with_id", comment.replies[0])
        self.assertIn("$unpaid", comment.replies[0])
        self.assertIn("$refunded", comment.replies[0])

    def test_non_verified_lender_is_rejected(self):
        fake_db = FakeDb()
        comment = run_loan_command(fake_db, "$loan 50 USD u/borrower", flair_text="Regular User")

        self.assertEqual(len(fake_db.loans), 0)
        self.assertIn("Verified Lender", comment.replies[0])

    def test_lender_cannot_loan_to_themselves(self):
        fake_db = FakeDb()
        comment = run_loan_command(fake_db, "$loan 50 USD u/lender", author_name="lender")

        self.assertEqual(len(fake_db.loans), 0)
        self.assertIn("cannot lend to yourself", comment.replies[0])

    def test_zero_amount_is_rejected(self):
        fake_db = FakeDb()
        comment = run_loan_command(fake_db, "$loan 0 USD u/borrower")

        self.assertEqual(len(fake_db.loans), 0)
        self.assertIn("greater than zero", comment.replies[0])

    def test_missing_borrower_gets_no_reply(self):
        fake_db = FakeDb()
        comment = run_loan_command(fake_db, "$loan 50 USD")

        self.assertEqual(len(fake_db.loans), 0)
        self.assertEqual(len(comment.replies), 0)

    def test_duplicate_loan_is_blocked(self):
        fake_db = FakeDb(loans=[
            loan_record(lender="lender", borrower="borrower", amount="50.00", currency="USD", status="confirmed")
        ])
        comment = run_loan_command(fake_db, "$loan 50 USD u/borrower")

        self.assertEqual(len(fake_db.loans), 1)
        self.assertIn("Error", comment.replies[0])

    def test_user_stats_updated_on_loan_creation(self):
        fake_db = FakeDb()
        run_loan_command(fake_db, "$loan 75 USD u/borrower")

        self.assertEqual(fake_db.users["lender"]["loans_as_lender"], 1)
        self.assertEqual(fake_db.users["lender"]["amount_lent"], Decimal("75"))
        self.assertEqual(fake_db.users["borrower"]["loans_as_borrower"], 1)
        self.assertEqual(fake_db.users["borrower"]["amount_borrowed"], Decimal("75"))

    def test_valid_due_date_creates_loan(self):
        fake_db = FakeDb()
        comment = run_loan_command(fake_db, "$loan 100 USD u/borrower due:30d")
        self.assertEqual(len(fake_db.loans), 1)
        self.assertIsNotNone(fake_db.loans[0].get("due_date"))
        self.assertIn("Loan recorded", comment.replies[0])

    def test_due_date_shown_in_reply(self):
        fake_db = FakeDb()
        comment = run_loan_command(fake_db, "$loan 100 USD u/borrower due:7d")
        self.assertEqual(len(fake_db.loans), 1)
        self.assertIn("Due Date", comment.replies[0])

    def test_due_date_weeks(self):
        fake_db = FakeDb()
        comment = run_loan_command(fake_db, "$loan 50 USD u/borrower due:2w")
        self.assertEqual(len(fake_db.loans), 1)
        self.assertIsNotNone(fake_db.loans[0].get("due_date"))

    def test_invalid_due_date_rejected(self):
        fake_db = FakeDb()
        comment = run_loan_command(fake_db, "$loan 50 USD u/borrower due:abc")
        # Invalid format — loan should NOT be created
        self.assertEqual(len(fake_db.loans), 0)
        self.assertIn("Invalid due date", comment.replies[0])

    def test_zero_due_date_rejected(self):
        fake_db = FakeDb()
        comment = run_loan_command(fake_db, "$loan 50 USD u/borrower due:0d")
        self.assertEqual(len(fake_db.loans), 0)
        self.assertIn("Invalid due date", comment.replies[0])


class DueDateParseTests(unittest.TestCase):
    """Unit tests for _parse_due_date helper."""

    def setUp(self):
        from commands.loan_command import _parse_due_date
        self._parse = _parse_due_date

    def test_none_returns_none(self):
        self.assertIsNone(self._parse(None))

    def test_empty_string_returns_none(self):
        self.assertIsNone(self._parse(""))

    def test_30d_returns_future_date(self):
        from datetime import datetime, timedelta
        result = self._parse("30d")
        self.assertIsNotNone(result)
        self.assertGreater(result, datetime.now() + timedelta(days=29))

    def test_2w_returns_future_date(self):
        from datetime import datetime, timedelta
        result = self._parse("2w")
        self.assertIsNotNone(result)
        self.assertGreater(result, datetime.now() + timedelta(days=13))

    def test_1m_returns_future_date(self):
        from datetime import datetime, timedelta
        result = self._parse("1m")
        self.assertIsNotNone(result)
        self.assertGreater(result, datetime.now() + timedelta(days=29))

    def test_0d_returns_none(self):
        self.assertIsNone(self._parse("0d"))

    def test_0w_returns_none(self):
        self.assertIsNone(self._parse("0w"))

    def test_invalid_format_returns_none(self):
        self.assertIsNone(self._parse("abc"))
        self.assertIsNone(self._parse("30"))
        self.assertIsNone(self._parse("30x"))


if __name__ == "__main__":
    unittest.main()
