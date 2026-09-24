import os
import importlib
import unittest
from unittest.mock import patch

from tests.support.fakes import FakeComment, FakeSubreddit


class FundCommandTests(unittest.TestCase):
    def run_fund_command(self, body, is_verified_lender=True, flair_text="Verified Lender"):
        comment = FakeComment(body=body, author_name="lender", subreddit=FakeSubreddit(flair_text=flair_text))
        fund_command = importlib.import_module("commands.fund_command")
        vl_return = (True, None, None) if is_verified_lender else (False, None, None)
        with patch("services.get_request_summary") as get_req, \
             patch("services.fund_loan_request") as fund_req, \
             patch("services.update_last_login"), \
             patch("services.get_verified_lender_status", return_value=vl_return):
            get_req.return_value = ({
                "request_id": "REQ-0001",
                "borrower": "borrower",
                "amount": 100,
                "currency": "USD",
                "status": "open",
            }, None)
            fund_req.return_value = ("1700001234", None)
            fund_command.process_fund_command(comment)
            return comment, get_req, fund_req

    def test_the_code_alone_funds_the_requested_amount(self):
        comment, get_req, fund_req = self.run_fund_command("$fund REQ-0001")

        get_req.assert_called_once_with("REQ-0001")
        fund_req.assert_called_once_with("REQ-0001", "lender", amount=None, currency=None)
        self.assertIn("Paid ID", comment.replies[0])
        self.assertIn("1700001234", comment.replies[0])
        self.assertIn("100.00 USD", comment.replies[0])
        self.assertIn("$paid_with_id 1700001234", comment.replies[0])
        self.assertNotIn("Due Date", comment.replies[0])

    def test_a_currency_after_the_code_changes_the_currency(self):
        comment, _get_req, fund_req = self.run_fund_command("$fund REQ-0001 CAD")

        fund_req.assert_called_once_with("REQ-0001", "lender", amount=None, currency="CAD")
        self.assertIn("100.00 CAD", comment.replies[0])
        self.assertIn("the request asked for 100.00 USD", comment.replies[0])

    def test_an_amount_overrides_what_the_request_asked_for(self):
        comment, _get_req, fund_req = self.run_fund_command("$fund REQ-0001 300USD")

        fund_req.assert_called_once_with("REQ-0001", "lender", amount="300", currency="USD")
        self.assertIn("300.00 USD", comment.replies[0])
        self.assertIn("the request asked for 100.00 USD", comment.replies[0])

    def test_old_style_repay_and_date_are_read_as_the_amount_only(self):
        _comment, _get_req, fund_req = self.run_fund_command("$fund REQ-0001 125 USD 2026-06-30")

        fund_req.assert_called_once_with("REQ-0001", "lender", amount="125", currency="USD")

    def test_a_non_currency_word_is_ignored(self):
        _comment, _get_req, fund_req = self.run_fund_command("$fund REQ-0001 now please")

        fund_req.assert_called_once_with("REQ-0001", "lender", amount=None, currency=None)

    def test_no_code_gets_no_reply(self):
        comment = FakeComment(body="$fund please", author_name="lender")
        fund_command = importlib.import_module("commands.fund_command")

        fund_command.process_fund_command(comment)

        self.assertEqual(comment.replies, [])


if __name__ == "__main__":
    unittest.main()
