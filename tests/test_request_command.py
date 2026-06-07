"""
Tests for $request lender — user submits a lender role request via bot.
"""
import importlib
import sys
import unittest
from unittest.mock import patch

from tests.support.fakes import FakeComment, FakeDb, fake_utils_module


class RequestCommandTests(unittest.TestCase):
    def _run(self, fake_db, body, author_name="user1",
             user_role="borrower"):
        fake_utils = fake_utils_module(fake_db)
        with patch.dict(sys.modules, {"utils": fake_utils}):
            # Patch get_user_role and submit_role_request
            with patch("services.get_user_role", return_value=(user_role, None)), \
                 patch("services.submit_role_request", return_value=(True, None)) as mock_submit, \
                 patch("services._get_db", fake_db.connection):
                cmd = importlib.import_module("commands.request_command")
                importlib.reload(cmd)
                comment = FakeComment(body=body, author_name=author_name)
                cmd.process_request_command(comment)
                return comment, mock_submit

    def test_request_lender_success(self):
        fake_db = FakeDb()
        comment, mock_submit = self._run(fake_db, "$request lender I have 3 years experience")
        self.assertTrue(len(comment.replies) > 0)
        self.assertIn("lender", comment.replies[0].lower())
        self.assertIn("submitted", comment.replies[0].lower())
        mock_submit.assert_called_once()

    def test_request_with_reason(self):
        fake_db = FakeDb()
        comment, mock_submit = self._run(fake_db, "$request lender been on r/borrow 2 years")
        mock_submit.assert_called_once()
        call_args = mock_submit.call_args[0]
        self.assertIn("been on r/borrow", call_args[2])

    def test_already_lender_no_request(self):
        fake_db = FakeDb()
        comment, mock_submit = self._run(fake_db, "$request lender", user_role="lender")
        self.assertIn("already", comment.replies[0].lower())
        mock_submit.assert_not_called()

    def test_already_mod_no_request(self):
        fake_db = FakeDb()
        comment, mock_submit = self._run(fake_db, "$request lender", user_role="mod")
        self.assertIn("already", comment.replies[0].lower())
        mock_submit.assert_not_called()

    def test_mod_request_rejected(self):
        fake_db = FakeDb()
        comment, mock_submit = self._run(fake_db, "$request mod", user_role="borrower")
        self.assertIn("moderator", comment.replies[0].lower())
        mock_submit.assert_not_called()

    def test_no_role_in_command_shows_usage(self):
        fake_db = FakeDb()
        comment, mock_submit = self._run(fake_db, "$request")
        self.assertIn("Usage", comment.replies[0])
        mock_submit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
