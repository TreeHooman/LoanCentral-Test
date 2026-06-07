"""Tests for $dispute command."""
import sys
import importlib
import unittest
from unittest.mock import patch

from tests.support.fakes import FakeComment, FakeDb, fake_utils_module


class TestDisputeCommand(unittest.TestCase):

    def _run(self, body, username, loans=None):
        db = FakeDb(loans=loans or [])
        with patch.dict(sys.modules, {"utils": fake_utils_module(db)}):
            mod = importlib.import_module("commands.dispute_command")
            comment = FakeComment(body=body, author_name=username)
            mod.handle_dispute(comment, username)
        return comment

    def _loan(self, **kw):
        base = {
            "id": 1, "loan_id": "LC-001", "lender": "lender1",
            "borrower": "borrower1", "amount": 200, "amount_repaid": 0,
            "currency": "USD", "status": "confirmed",
        }
        base.update(kw)
        return base

    def test_borrower_can_dispute(self):
        loans = [self._loan()]
        c = self._run("$dispute LC-001", "borrower1", loans)
        self.assertIn("disputed", c.reply_text.lower())

    def test_wrong_borrower_rejected(self):
        loans = [self._loan()]
        c = self._run("$dispute LC-001", "wronguser", loans)
        self.assertIsNotNone(c.reply_text)
        self.assertIn("couldn't", c.reply_text.lower())
        self.assertEqual(loans[0]["status"], "confirmed")

    def test_already_disputed_blocked(self):
        loans = [self._loan(status="disputed")]
        c = self._run("$dispute LC-001", "borrower1", loans)
        self.assertIn("already", c.reply_text.lower())

    def test_repaid_loan_cannot_be_disputed(self):
        loans = [self._loan(status="repaid")]
        c = self._run("$dispute LC-001", "borrower1", loans)
        self.assertIsNotNone(c.reply_text)
        self.assertIn("closed", c.reply_text.lower())

    def test_missing_id_no_reply(self):
        c = self._run("$dispute", "borrower1")
        self.assertIsNone(c.reply_text)


if __name__ == "__main__":
    unittest.main()
