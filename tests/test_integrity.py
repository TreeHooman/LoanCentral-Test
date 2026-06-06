import unittest
from decimal import Decimal

from integrity import calculate_user_totals, find_integrity_issues
from tests.support.fakes import loan_record


class IntegrityTests(unittest.TestCase):
    def test_calculates_expected_user_totals_from_loans(self):
        loans = [
            loan_record(db_id=1, lender="lender", borrower="borrower", amount="100", amount_repaid="40"),
            loan_record(db_id=2, lender="lender", borrower="borrower", amount="50", amount_repaid="10", status="unpaid"),
            loan_record(db_id=3, lender="lender", borrower="borrower", amount="20", status="refunded"),
        ]

        totals = calculate_user_totals(loans)

        self.assertEqual(totals["lender"]["loans_as_lender"], 2)
        self.assertEqual(totals["lender"]["amount_lent"], Decimal("150"))
        self.assertEqual(totals["borrower"]["loans_as_borrower"], 2)
        self.assertEqual(totals["borrower"]["amount_borrowed"], Decimal("150"))
        self.assertEqual(totals["borrower"]["amount_repaid"], Decimal("50.00"))
        self.assertEqual(totals["borrower"]["unpaid_loans"], 1)
        self.assertEqual(totals["borrower"]["unpaid_amount"], Decimal("40.00"))

    def test_reports_loan_integrity_issues(self):
        loans = [
            loan_record(db_id=1, amount="100", amount_repaid="125"),
            loan_record(db_id=2, amount="50", amount_repaid="25", status="repaid"),
            loan_record(db_id=3, amount="50", amount_repaid="50", status="unpaid"),
            loan_record(db_id=4, amount="0", status="confirmed"),
            loan_record(db_id=5, status="bad_status"),
        ]

        issues = find_integrity_issues(loans, users={})

        self.assertTrue(any("amount_repaid exceeds amount" in issue for issue in issues))
        self.assertTrue(any("status repaid but amount is not fully repaid" in issue for issue in issues))
        self.assertTrue(any("status unpaid but loan is fully repaid" in issue for issue in issues))
        self.assertTrue(any("amount must be greater than zero" in issue for issue in issues))
        self.assertTrue(any("invalid status" in issue for issue in issues))

    def test_reports_user_total_mismatches(self):
        loans = [loan_record(db_id=1, lender="lender", borrower="borrower", amount="100", amount_repaid="40")]
        users = {
            "lender": {"loans_as_lender": 99, "amount_lent": Decimal("999")},
            "borrower": {"loans_as_borrower": 1, "amount_borrowed": Decimal("100"), "amount_repaid": Decimal("0")},
        }

        issues = find_integrity_issues(loans, users)

        self.assertTrue(any("User lender: loans_as_lender is 99, expected 1" in issue for issue in issues))
        self.assertTrue(any("User borrower: amount_repaid is 0" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()
