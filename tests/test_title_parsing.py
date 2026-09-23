"""[REQ] title parsing.

If the principal does not parse, save_loan_request refuses the post and the
request never exists — the whole dashboard funding flow is unavailable for it.
The old parser only found an amount inside parentheses, so "[REQ] $150 - City"
was silently dropped. It also only recognised "Repay", not "Payback" or
"Pay back". Both gaps were flagged in NEXT_SESSION.txt as pre-launch work.
"""

import unittest
from datetime import datetime

import services
from services import _parse_req_title as parse
from tests.support.dbcase import RealDBTestCase


class PrincipalTests(unittest.TestCase):

    def test_parenthesised_amount(self):
        self.assertEqual(parse("[REQ] ($150) (#Denver, CO, USA) (Repay $180) (10/15)")["amount"], 150.0)

    def test_bare_dollar_amount(self):
        self.assertEqual(parse("[REQ] $150 - Denver, CO, USA - Repay $180 by 10/15")["amount"], 150.0)

    def test_bare_amount_next_to_a_parenthesised_location(self):
        self.assertEqual(parse("[REQ] $50 (#Reno, NV, USA) (Repay $60) (10/20)")["amount"], 50.0)

    def test_thousands_separator(self):
        self.assertEqual(parse("[REQ] ($1,200) (#Austin, TX) (Repay $1,400) (11/01)")["amount"], 1200.0)

    def test_bare_currency_suffix(self):
        result = parse("[REQ] 75 CAD (#Calgary, AB) repayment 90 CAD 10/30")
        self.assertEqual((result["amount"], result["currency"]), (75.0, "CAD"))

    def test_repay_amount_listed_first_is_not_taken_as_the_principal(self):
        result = parse("[REQ] Repay $240 - need $200 (#Tulsa, OK) 10/15")
        self.assertEqual((result["amount"], result["repay_amount"]), (200.0, 240.0))

    def test_a_zip_code_is_not_a_loan_amount(self):
        """Only currency-marked numbers count outside parentheses."""
        result = parse("[REQ] (#Miami, FL 33101) need help, repay $120 on 10/15")
        self.assertIsNone(result["amount"])
        self.assertEqual(result["repay_amount"], 120.0)


class RepaymentTests(unittest.TestCase):

    def test_repay(self):
        self.assertEqual(parse("[REQ] ($150) (Repay $180) (10/15)")["repay_amount"], 180.0)

    def test_payback(self):
        self.assertEqual(parse("[REQ] ($150) (Payback $180) (10/15)")["repay_amount"], 180.0)

    def test_pay_back_two_words(self):
        self.assertEqual(parse("[REQ] ($150) (Pay back $180 on 10/15)")["repay_amount"], 180.0)

    def test_repayment(self):
        self.assertEqual(parse("[REQ] ($150) (Repayment: $180) (10/15)")["repay_amount"], 180.0)

    def test_repay_with_currency_code(self):
        self.assertEqual(parse("[REQ] (150 USD) (Repay 180 USD) (10/15)")["repay_amount"], 180.0)

    def test_unlabelled_second_amount_is_not_guessed(self):
        """LoanCentral does not infer loan terms; the lender enters them."""
        self.assertIsNone(parse("[REQ] ($200) (#Tampa, FL) ($250 on 10/30)")["repay_amount"])


class BareTitlesAreSavedTests(RealDBTestCase):
    """The consequence that matters: these posts now become requests."""

    def test_bare_dollar_post_is_saved(self):
        request_id, error = services.save_loan_request(
            "borrower", "[REQ] $150 - Denver, CO, USA - Repay $180 by 10/15",
            "https://example.com/p", datetime.now(), "bare1")
        self.assertIsNone(error, error)
        amount = self.query(
            "SELECT requested_amount, requested_repayment_amount FROM loan_requests "
            "WHERE request_id = %s", (request_id,))[0]
        self.assertEqual((float(amount[0]), float(amount[1])), (150.0, 180.0))

    def test_post_with_no_amount_is_still_refused(self):
        request_id, error = services.save_loan_request(
            "borrower", "[REQ] (#Miami, FL 33101) need help asap",
            "https://example.com/p", datetime.now(), "bare2")
        self.assertIsNone(request_id)
        self.assertIn("amount", error)
