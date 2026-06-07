"""Tests for $ban and $unban commands."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.support.fakes import FakeComment, FakeDb, FakeReddit, FakeSubreddit

FAKE_DB = None


def _patch_db(fake):
    return patch("services._get_db", side_effect=lambda: fake.connection())


class BanCommandTests(unittest.TestCase):
    def setUp(self):
        self.fake_db = FakeDb()
        self.sub = FakeSubreddit(flair_text="Mod")

    def _comment(self, body, author="moduser"):
        return FakeComment(body, author_name=author, subreddit=self.sub)

    def test_non_mod_cannot_ban(self):
        plain_sub = FakeSubreddit(flair_text="Lender")
        comment = FakeComment("$ban u/someuser", author_name="lender1", subreddit=plain_sub)
        with _patch_db(self.fake_db):
            from commands.ban_command import process_ban_command
            process_ban_command(comment)
        self.assertEqual(len(comment.replies), 1)
        self.assertIn("moderators", comment.replies[0].lower())

    def test_mod_can_ban_user(self):
        comment = self._comment("$ban u/baduser spamming")
        with _patch_db(self.fake_db):
            from commands.ban_command import process_ban_command
            process_ban_command(comment)
        self.assertEqual(len(comment.replies), 1)
        self.assertIn("banned", comment.replies[0].lower())
        self.assertIn("baduser", comment.replies[0])
        self.assertIn("baduser", self.fake_db.bans)

    def test_ban_reply_includes_reason(self):
        comment = self._comment("$ban u/spammer repeated scam attempts")
        with _patch_db(self.fake_db):
            from commands.ban_command import process_ban_command
            process_ban_command(comment)
        self.assertIn("repeated scam attempts", comment.replies[0])

    def test_cannot_ban_self(self):
        comment = self._comment("$ban u/moduser", author="moduser")
        with _patch_db(self.fake_db):
            from commands.ban_command import process_ban_command
            process_ban_command(comment)
        self.assertIn("yourself", comment.replies[0].lower())
        self.assertNotIn("moduser", self.fake_db.bans)

    def test_no_match_no_reply(self):
        comment = self._comment("just a regular comment")
        with _patch_db(self.fake_db):
            from commands.ban_command import process_ban_command
            process_ban_command(comment)
        self.assertEqual(len(comment.replies), 0)

    def test_ban_triggers_discord_notify(self):
        comment = self._comment("$ban u/cheater")
        with _patch_db(self.fake_db), \
             patch("notifications.notify_discord") as mock_discord:
            from commands.ban_command import process_ban_command
            process_ban_command(comment)
        mock_discord.assert_called_once()
        call_arg = mock_discord.call_args[0][0]
        self.assertIn("cheater", call_arg.lower())


class UnbanCommandTests(unittest.TestCase):
    def setUp(self):
        self.fake_db = FakeDb(bans={"oldban": {"username": "oldban", "reason": "test", "banned_by": "moduser"}})
        self.sub = FakeSubreddit(flair_text="Mod")

    def _comment(self, body, author="moduser"):
        return FakeComment(body, author_name=author, subreddit=self.sub)

    def test_mod_can_unban(self):
        comment = self._comment("$unban u/oldban")
        with _patch_db(self.fake_db):
            from commands.unban_command import process_unban_command
            process_unban_command(comment)
        self.assertEqual(len(comment.replies), 1)
        self.assertIn("unbanned", comment.replies[0].lower())
        self.assertNotIn("oldban", self.fake_db.bans)

    def test_unban_not_banned_user_replies_error(self):
        comment = self._comment("$unban u/notbanned")
        with _patch_db(self.fake_db):
            from commands.unban_command import process_unban_command
            process_unban_command(comment)
        self.assertEqual(len(comment.replies), 1)
        self.assertIn("not banned", comment.replies[0].lower())

    def test_non_mod_cannot_unban(self):
        plain_sub = FakeSubreddit(flair_text="Lender")
        comment = FakeComment("$unban u/oldban", author_name="lender1", subreddit=plain_sub)
        with _patch_db(self.fake_db):
            from commands.unban_command import process_unban_command
            process_unban_command(comment)
        self.assertIn("moderators", comment.replies[0].lower())
        self.assertIn("oldban", self.fake_db.bans)

    def test_no_match_no_reply(self):
        comment = self._comment("just a comment")
        with _patch_db(self.fake_db):
            from commands.unban_command import process_unban_command
            process_unban_command(comment)
        self.assertEqual(len(comment.replies), 0)


class BanEnforcementTests(unittest.TestCase):
    """Banned users cannot create loans."""

    def setUp(self):
        self.fake_db = FakeDb(
            bans={"bannedlender": {"username": "bannedlender", "reason": "scam", "banned_by": "moduser"}}
        )

    def test_banned_lender_cannot_create_loan(self):
        comment = FakeComment("$loan 50 USD u/borrower1", author_name="bannedlender")
        with _patch_db(self.fake_db):
            from commands.loan_command import process_loan_command
            process_loan_command(comment)
        self.assertEqual(len(comment.replies), 1)
        self.assertIn("suspended", comment.replies[0].lower())
        self.assertEqual(len(self.fake_db.loans), 0)

    def test_non_banned_lender_can_create_loan(self):
        self.fake_db.users["goodlender"] = {"flair": "Verified Lender"}
        comment = FakeComment("$loan 50 USD u/borrower1", author_name="goodlender")
        with _patch_db(self.fake_db):
            from commands.loan_command import process_loan_command
            process_loan_command(comment)
        # Should not reply with suspension message
        suspension_replies = [r for r in comment.replies if "suspended" in r.lower()]
        self.assertEqual(len(suspension_replies), 0)


if __name__ == "__main__":
    unittest.main()
