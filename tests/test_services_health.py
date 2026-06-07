"""
Tests for credit_tier() and calculate_health_score() — pure functions, no DB needed.
"""
import sys
import os
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import credit_tier, calculate_health_score


class CreditTierTests(unittest.TestCase):
    def test_trusted_borrower(self):
        t = credit_tier(95)
        self.assertEqual(t["label"], "Trusted Borrower")
        self.assertEqual(t["color"], "green")

    def test_trusted_boundary(self):
        self.assertEqual(credit_tier(90)["label"], "Trusted Borrower")

    def test_good_standing(self):
        self.assertEqual(credit_tier(89)["label"], "Good Standing")
        self.assertEqual(credit_tier(70)["label"], "Good Standing")

    def test_fair_standing(self):
        self.assertEqual(credit_tier(69)["label"], "Fair Standing")
        self.assertEqual(credit_tier(50)["label"], "Fair Standing")

    def test_at_risk(self):
        self.assertEqual(credit_tier(49)["label"], "At Risk")
        self.assertEqual(credit_tier(25)["label"], "At Risk")

    def test_high_risk(self):
        self.assertEqual(credit_tier(24)["label"], "High Risk")
        self.assertEqual(credit_tier(0)["label"], "High Risk")

    def test_all_tiers_have_color(self):
        for score in (0, 25, 50, 70, 90, 100):
            t = credit_tier(score)
            self.assertIn("color", t)
            self.assertIn("label", t)


class CalculateHealthScoreTests(unittest.TestCase):
    def _profile(self, loans=0, unpaid=0, borrowed="0", repaid="0"):
        return {
            "loans_as_borrower": loans,
            "unpaid_loans": unpaid,
            "amount_borrowed": Decimal(borrowed),
            "amount_repaid": Decimal(repaid),
        }

    def test_no_history(self):
        score, label = calculate_health_score(self._profile())
        self.assertEqual(score, 100)
        self.assertEqual(label, "No history")

    def test_perfect_repayment(self):
        score, label = calculate_health_score(self._profile(5, 0, "500", "500"))
        self.assertEqual(score, 100)
        self.assertEqual(label, "Excellent")

    def test_all_unpaid(self):
        score, label = calculate_health_score(self._profile(5, 5, "500", "0"))
        self.assertEqual(score, 0)
        self.assertEqual(label, "Very Poor")

    def test_half_unpaid(self):
        # loan_ratio = 0.5, pay_ratio = 0.0 → (0.5 * 0.7 + 0.0 * 0.3) * 100 = 35
        # calculate_health_score labels: Poor = 25-49, distinct from credit_tier "At Risk"
        score, label = calculate_health_score(self._profile(4, 2, "400", "0"))
        self.assertEqual(score, 35)
        self.assertEqual(label, "Poor")

    def test_good_score(self):
        # All loans paid, repaid 90% of amount: loan_ratio=1.0, pay_ratio=0.9
        # (1.0*0.7 + 0.9*0.3)*100 = (0.7 + 0.27)*100 = 97 → Excellent
        score, label = calculate_health_score(self._profile(3, 0, "100", "90"))
        self.assertEqual(score, 97)
        self.assertEqual(label, "Excellent")

    def test_repayment_capped_at_100(self):
        # Over-repaid edge case: repaid > borrowed → pay_ratio capped at 1.0
        score, label = calculate_health_score(self._profile(2, 0, "100", "120"))
        self.assertEqual(score, 100)

    def test_score_is_integer(self):
        score, _ = calculate_health_score(self._profile(3, 1, "300", "150"))
        self.assertIsInstance(score, int)


if __name__ == "__main__":
    unittest.main()
