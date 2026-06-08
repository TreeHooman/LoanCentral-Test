import importlib
import unittest
from unittest.mock import patch

from tests.support.fakes import FakeComment, FakeSubreddit


class FundCommandTests(unittest.TestCase):
    def run_fund_command(self, body, flair_text="Verified Lender"):
        subreddit = FakeSubreddit(flair_text=flair_text)
        comment = FakeComment(body=body, author_name="lender", subreddit=subreddit)
        fund_command = importlib.import_module("commands.fund_command")
        with patch("services.get_loan_request") as get_req, \
             patch("services.fund_loan_request") as fund_req, \
             patch("services.update_last_login"):
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

    def test_verified_lender_can_fund_req_and_get_paid_id(self):
        comment, get_req, fund_req = self.run_fund_command("$fund REQ-0001 125 USD 2026-06-30")

        get_req.assert_called_once_with("REQ-0001")
        fund_req.assert_called_once_with("REQ-0001", "lender", 125.0, "2026-06-30")
        self.assertIn("Paid ID", comment.replies[0])
        self.assertIn("1700001234", comment.replies[0])
        self.assertIn("$paid_with_id 1700001234", comment.replies[0])

    def test_non_verified_lender_is_rejected(self):
        comment, _get_req, fund_req = self.run_fund_command("$fund REQ-0001 125 USD 2026-06-30", flair_text="Regular")

        fund_req.assert_not_called()
        self.assertIn("Verified Lender", comment.replies[0])

    def test_currency_mismatch_is_rejected(self):
        comment = FakeComment(body="$fund REQ-0001 125 CAD 2026-06-30", author_name="lender")
        fund_command = importlib.import_module("commands.fund_command")
        with patch("services.get_loan_request") as get_req, \
             patch("services.fund_loan_request") as fund_req, \
             patch("services.update_last_login"):
            get_req.return_value = ({
                "request_id": "REQ-0001",
                "borrower": "borrower",
                "amount": 100,
                "currency": "USD",
                "status": "open",
            }, None)
            fund_command.process_fund_command(comment)

        fund_req.assert_not_called()
        self.assertIn("Currency mismatch", comment.replies[0])

    def test_missing_args_gets_no_reply(self):
        comment = FakeComment(body="$fund REQ-0001", author_name="lender")
        fund_command = importlib.import_module("commands.fund_command")

        fund_command.process_fund_command(comment)

        self.assertEqual(comment.replies, [])


if __name__ == "__main__":
    unittest.main()
