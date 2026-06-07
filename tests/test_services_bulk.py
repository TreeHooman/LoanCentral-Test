"""
Tests for bulk_loan_action() — mod bulk unpaid/refunded operations.
"""
import sys
import os
import unittest
from decimal import Decimal
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services
from tests.support.fakes import FakeDb, fake_utils_module, loan_record


def _setup(monkeypatch, loans=None, users=None):
    fake_db = FakeDb(loans=loans or [], users=users or {})
    monkeypatch.setattr("services._get_db", fake_db.connection)
    return fake_db


class BulkLoanActionTests(unittest.TestCase):
    def _db(self, loans, users=None):
        return FakeDb(loans=loans, users=users or {})

    def _run(self, fake_db, loan_ids, action, actor="mod"):
        with patch("services._get_db", fake_db.connection):
            return services.bulk_loan_action(loan_ids, action, actor)

    # ---- invalid params -------------------------------------------------------

    def test_empty_ids_returns_error(self):
        fake_db = self._db([])
        result = self._run(fake_db, [], "unpaid")
        self.assertIn("Invalid parameters", result["errors"][0])

    def test_invalid_action_returns_error(self):
        fake_db = self._db([])
        result = self._run(fake_db, [1], "delete")
        self.assertIn("Invalid parameters", result["errors"][0])

    # ---- bulk unpaid ----------------------------------------------------------

    def test_bulk_unpaid_single_loan(self):
        loan = loan_record(db_id=10, lender="lender1", borrower="bob",
                           amount="200.00", status="confirmed")
        fake_db = self._db(
            [loan],
            users={"bob": {"unpaid_loans": 0, "unpaid_amount": Decimal("0")}},
        )
        result = self._run(fake_db, [10], "unpaid")
        self.assertEqual(result["success"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(fake_db.find_loan(10)["status"], "unpaid")

    def test_bulk_unpaid_multiple_loans(self):
        loans = [
            loan_record(db_id=1, lender="lend", borrower="borrow1",
                        amount="100.00", status="confirmed"),
            loan_record(db_id=2, public_id="9999", lender="lend",
                        borrower="borrow2", amount="50.00", status="confirmed"),
        ]
        fake_db = self._db(
            loans,
            users={
                "borrow1": {"unpaid_loans": 0, "unpaid_amount": Decimal("0")},
                "borrow2": {"unpaid_loans": 0, "unpaid_amount": Decimal("0")},
            },
        )
        result = self._run(fake_db, [1, 2], "unpaid")
        self.assertEqual(result["success"], 2)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(fake_db.find_loan(1)["status"], "unpaid")
        self.assertEqual(fake_db.find_loan(2)["status"], "unpaid")

    def test_bulk_unpaid_nonexistent_loan_counts_as_failure(self):
        fake_db = self._db([])
        result = self._run(fake_db, [999], "unpaid")
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["success"], 0)

    def test_bulk_capped_at_50_ids(self):
        """bulk_loan_action should silently process at most 50 IDs."""
        loans = [
            loan_record(db_id=i, lender="lend", borrower="borrow",
                        amount="10.00", status="confirmed")
            for i in range(1, 101)
        ]
        fake_db = self._db(
            loans,
            users={"borrow": {"unpaid_loans": 0, "unpaid_amount": Decimal("0")}},
        )
        ids = list(range(1, 101))  # 100 IDs
        result = self._run(fake_db, ids, "unpaid")
        # Hard cap: only first 50 processed
        self.assertEqual(result["success"], 50)

    # ---- bulk refunded --------------------------------------------------------

    def test_bulk_refunded_single_loan(self):
        loan = loan_record(db_id=5, lender="lend", borrower="borrow",
                           amount="75.00", status="confirmed")
        fake_db = self._db(
            [loan],
            users={
                "lend":   {"loans_as_lender": 1, "amount_lent": Decimal("75")},
                "borrow": {"loans_as_borrower": 1, "amount_borrowed": Decimal("75")},
            },
        )
        result = self._run(fake_db, [5], "refunded")
        self.assertEqual(result["success"], 1)
        self.assertEqual(fake_db.find_loan(5)["status"], "refunded")


if __name__ == "__main__":
    unittest.main()
