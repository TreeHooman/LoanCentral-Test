"""
Tests for get_loan_history() and get_active_loans() in services.py.
"""
import importlib
import sys
import unittest
from decimal import Decimal
from unittest.mock import patch

from tests.support.fakes import FakeDb, fake_utils_module, loan_record


class GetLoanHistoryTests(unittest.TestCase):
    def _call(self, fake_db, username, role="both", limit=50):
        with patch.dict(sys.modules, {"utils": fake_utils_module(fake_db)}):
            import services
            importlib.reload(services)
            return services.get_loan_history(username, role=role, limit=limit)

    def test_returns_empty_list_for_unknown_user(self):
        fake_db = FakeDb(loans=[], users={})
        loans, error = self._call(fake_db, "nobody")
        self.assertIsNone(error)
        self.assertEqual(loans, [])

    def test_returns_loans_where_user_is_borrower(self):
        fake_db = FakeDb(loans=[
            loan_record(db_id=1, lender="alice", borrower="bob"),
            loan_record(db_id=2, lender="bob", borrower="carol"),
        ])
        loans, error = self._call(fake_db, "bob", role="borrower")
        self.assertIsNone(error)
        self.assertEqual(len(loans), 1)
        self.assertEqual(loans[0]["db_id"], 1)

    def test_returns_loans_where_user_is_lender(self):
        fake_db = FakeDb(loans=[
            loan_record(db_id=1, lender="alice", borrower="bob"),
            loan_record(db_id=2, lender="bob", borrower="carol"),
        ])
        loans, error = self._call(fake_db, "bob", role="lender")
        self.assertIsNone(error)
        self.assertEqual(len(loans), 1)
        self.assertEqual(loans[0]["db_id"], 2)

    def test_returns_all_loans_for_both_roles(self):
        fake_db = FakeDb(loans=[
            loan_record(db_id=1, lender="alice", borrower="bob"),
            loan_record(db_id=2, lender="bob", borrower="carol"),
            loan_record(db_id=3, lender="dave", borrower="eve"),
        ])
        loans, error = self._call(fake_db, "bob", role="both")
        self.assertIsNone(error)
        self.assertEqual(len(loans), 2)
        db_ids = {loan["db_id"] for loan in loans}
        self.assertEqual(db_ids, {1, 2})

    def test_loan_dict_has_expected_fields(self):
        fake_db = FakeDb(loans=[loan_record(db_id=7, amount="75.00")])
        loans, error = self._call(fake_db, "borrower", role="borrower")
        self.assertIsNone(error)
        self.assertEqual(len(loans), 1)
        loan = loans[0]
        self.assertEqual(loan["db_id"], 7)
        self.assertEqual(loan["amount"], Decimal("75.00"))
        self.assertIn("lender", loan)
        self.assertIn("borrower", loan)
        self.assertIn("currency", loan)
        self.assertIn("status", loan)


class GetActiveLoansTests(unittest.TestCase):
    def _call(self, fake_db, username):
        with patch.dict(sys.modules, {"utils": fake_utils_module(fake_db)}):
            import services
            importlib.reload(services)
            return services.get_active_loans(username)

    def test_returns_empty_for_user_with_no_loans(self):
        fake_db = FakeDb(loans=[], users={})
        loans, error = self._call(fake_db, "nobody")
        self.assertIsNone(error)
        self.assertEqual(loans, [])

    def test_returns_confirmed_loans_only(self):
        fake_db = FakeDb(loans=[
            loan_record(db_id=1, borrower="bob", status="confirmed"),
            loan_record(db_id=2, borrower="bob", status="repaid"),
            loan_record(db_id=3, borrower="bob", status="partially_repaid"),
            loan_record(db_id=4, borrower="bob", status="unpaid"),
        ])
        loans, error = self._call(fake_db, "bob")
        self.assertIsNone(error)
        db_ids = {loan["db_id"] for loan in loans}
        self.assertEqual(db_ids, {1, 3})

    def test_active_loan_dict_includes_remaining(self):
        fake_db = FakeDb(loans=[
            loan_record(db_id=1, borrower="bob", amount="100.00", amount_repaid="30.00", status="partially_repaid"),
        ])
        loans, error = self._call(fake_db, "bob")
        self.assertIsNone(error)
        self.assertEqual(len(loans), 1)
        self.assertEqual(loans[0]["remaining"], Decimal("70.00"))

    def test_ignores_loans_for_other_borrowers(self):
        fake_db = FakeDb(loans=[
            loan_record(db_id=1, borrower="alice", status="confirmed"),
            loan_record(db_id=2, borrower="bob", status="confirmed"),
        ])
        loans, error = self._call(fake_db, "bob")
        self.assertIsNone(error)
        self.assertEqual(len(loans), 1)
        self.assertEqual(loans[0]["db_id"], 2)


if __name__ == "__main__":
    unittest.main()
