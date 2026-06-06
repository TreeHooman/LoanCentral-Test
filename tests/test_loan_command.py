import importlib
import sys
import unittest
from unittest.mock import patch

from tests.support.fakes import FakeComment, FakeDb, FakeSubmission, FakeSubreddit, fake_utils_module


class LoanCommandTests(unittest.TestCase):
    def run_loan_command(self, body, author_name="lender", borrower_name="borrower", flair_text="Verified Lender"):
        subreddit = FakeSubreddit(flair_text=flair_text)
        submission = FakeSubmission(author_name=borrower_name, subreddit=subreddit)
        comment = FakeComment(body=body, author_name=author_name, submission=submission, subreddit=subreddit)

        with patch.dict(sys.modules, {"utils": fake_utils_module(FakeDb())}):
            loan_command = importlib.import_module("commands.loan_command")
            loan_command.process_loan_command(comment)

        return comment

    def test_verified_lender_gets_confirm_instructions(self):
        comment = self.run_loan_command("$loan 75 USD")

        self.assertIn("offering 75.00 USD", comment.replies[0])
        self.assertIn("$confirm /u/lender 75.00 USD", comment.replies[0])

    def test_unverified_lender_is_blocked(self):
        comment = self.run_loan_command("$loan 75 USD", flair_text="New User")

        self.assertIn("Only users with 'Verified Lender' flair", comment.replies[0])

    def test_self_loan_gets_no_reply(self):
        comment = self.run_loan_command("$loan 75 USD", author_name="borrower", borrower_name="borrower")

        self.assertEqual(comment.replies, [])


if __name__ == "__main__":
    unittest.main()

