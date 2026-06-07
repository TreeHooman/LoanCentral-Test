"""Tests for the $status command."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.support.fakes import FakeComment, FakeDb, loan_record


def _patch_db(fake):
    return patch("services._get_db", side_effect=lambda: fake.connection())


class StatusCommandTests(unittest.TestCase):
    def setUp(self):
        self.fake_db = FakeDb(loans=[
            loan_record(db_id=1, status="confirmed"),
            loan_record(db_id=2, status="repaid"),
            loan_record(db_id=3, status="unpaid"),
        ])

    def _run(self, body="$status"):
        comment = FakeComment(body, author_name="user1")
        with _patch_db(self.fake_db), \
             patch("services.get_bot_status", return_value=None):
            from commands.status_command import process_status_command
            process_status_command(comment)
        return comment

    def test_replies_to_status(self):
        comment = self._run("$status")
        self.assertEqual(len(comment.replies), 1)

    def test_reply_mentions_database(self):
        comment = self._run()
        self.assertIn("database", comment.replies[0].lower())

    def test_reply_mentions_total_loans(self):
        comment = self._run()
        self.assertIn("3", comment.replies[0])

    def test_reply_mentions_active_loans(self):
        comment = self._run()
        # 1 confirmed loan = 1 active
        self.assertIn("1", comment.replies[0])

    def test_no_trigger_no_reply(self):
        comment = self._run("just chatting")
        self.assertEqual(len(comment.replies), 0)

    def test_case_insensitive_trigger(self):
        comment = self._run("$STATUS")
        self.assertEqual(len(comment.replies), 1)

    def test_with_heartbeat(self):
        from datetime import datetime, timezone
        comment = FakeComment("$status", author_name="user1")
        bot_info = {"last_heartbeat": datetime.now(timezone.utc).isoformat()}
        with _patch_db(self.fake_db), \
             patch("services.get_bot_status", return_value=bot_info):
            from commands.status_command import process_status_command
            process_status_command(comment)
        self.assertIn("running", comment.replies[0].lower())


if __name__ == "__main__":
    unittest.main()
