"""Tests for the $warn command."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.support.fakes import FakeComment, FakeDb, FakeSubreddit


def _patch_db(fake):
    return patch("services._get_db", side_effect=lambda: fake.connection())


# Suppress the DM send so tests don't need a real utils module
_NO_DM = patch("commands.warn_command.process_warn_command.__globals__", {})


def _run_warn(comment, fake_db):
    """Run warn command with DB patched and reddit DM suppressed."""
    mock_redditor = MagicMock()
    fake_reddit   = MagicMock()
    fake_reddit.redditor.return_value = mock_redditor
    with _patch_db(fake_db), \
         patch("utils.reddit", fake_reddit), \
         patch.dict("sys.modules", {"utils": MagicMock(reddit=fake_reddit)}):
        from commands import warn_command
        # Re-patch inside the module's namespace
        original = warn_command.__dict__.get("reddit", None)
        try:
            import importlib
            warn_command = importlib.reload(warn_command)
        except Exception:
            pass
        warn_command.process_warn_command(comment)
    return mock_redditor


class WarnCommandTests(unittest.TestCase):
    def setUp(self):
        self.fake_db   = FakeDb()
        self.mod_sub   = FakeSubreddit(flair_text="Mod")
        self.plain_sub = FakeSubreddit(flair_text="Lender")

    def _mod_comment(self, body, author="moduser"):
        return FakeComment(body, author_name=author, subreddit=self.mod_sub)

    def _run(self, comment):
        """Run warn command, mocking out the reddit DM."""
        mock_reddit = MagicMock()
        with _patch_db(self.fake_db), \
             patch.dict("sys.modules", {"utils": MagicMock(
                 reddit=mock_reddit,
                 get_db_connection=lambda: self.fake_db.connection()
             )}):
            from commands.warn_command import process_warn_command
            process_warn_command(comment)
        return mock_reddit

    def test_mod_can_warn_user(self):
        comment = self._mod_comment("$warn u/baduser rule violation")
        self._run(comment)
        self.assertEqual(len(comment.replies), 1)
        self.assertIn("warning issued", comment.replies[0].lower())

    def test_warn_reply_includes_reason(self):
        comment = self._mod_comment("$warn u/baduser repeated late repayment")
        self._run(comment)
        self.assertIn("repeated late repayment", comment.replies[0])

    def test_non_mod_cannot_warn(self):
        comment = FakeComment("$warn u/someone rule", author_name="lender1", subreddit=self.plain_sub)
        with _patch_db(self.fake_db):
            from commands.warn_command import process_warn_command
            process_warn_command(comment)
        self.assertIn("moderators", comment.replies[0].lower())

    def test_cannot_warn_self(self):
        comment = self._mod_comment("$warn u/moduser self warn")
        with _patch_db(self.fake_db):
            from commands.warn_command import process_warn_command
            process_warn_command(comment)
        self.assertIn("yourself", comment.replies[0].lower())

    def test_no_match_shows_usage(self):
        comment = self._mod_comment("$warn")
        with _patch_db(self.fake_db):
            from commands.warn_command import process_warn_command
            process_warn_command(comment)
        self.assertIn("usage", comment.replies[0].lower())

    def test_not_in_body_no_reply(self):
        comment = self._mod_comment("just chatting")
        with _patch_db(self.fake_db):
            from commands.warn_command import process_warn_command
            process_warn_command(comment)
        self.assertEqual(len(comment.replies), 0)

    def test_warn_logs_mod_note(self):
        comment = self._mod_comment("$warn u/testuser bad behaviour")
        self._run(comment)
        self.assertEqual(self.fake_db._next_note_id, 1)

    def test_discord_notify_on_warn(self):
        comment = self._mod_comment("$warn u/someone reason here")
        with _patch_db(self.fake_db), \
             patch.dict("sys.modules", {"utils": MagicMock(
                 reddit=MagicMock(),
                 get_db_connection=lambda: self.fake_db.connection()
             )}), \
             patch("notifications.notify_discord") as mock_discord:
            from commands.warn_command import process_warn_command
            process_warn_command(comment)
        mock_discord.assert_called_once()
        self.assertIn("warning", mock_discord.call_args[0][0].lower())


if __name__ == "__main__":
    unittest.main()
