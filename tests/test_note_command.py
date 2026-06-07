"""Tests for the $note command — mod notes on users."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.support.fakes import FakeComment, FakeDb, FakeSubreddit


def _patch_db(fake):
    return patch("services._get_db", side_effect=lambda: fake.connection())


class NoteCommandTests(unittest.TestCase):
    def setUp(self):
        self.fake_db = FakeDb()
        self.mod_sub = FakeSubreddit(flair_text="Mod")
        self.plain_sub = FakeSubreddit(flair_text="Lender")

    def _mod_comment(self, body):
        return FakeComment(body, author_name="moduser", subreddit=self.mod_sub)

    def test_mod_can_add_note(self):
        comment = self._mod_comment("$note u/someuser warning: spam")
        with _patch_db(self.fake_db):
            from commands.note_command import process_note_command
            process_note_command(comment)
        self.assertEqual(len(comment.replies), 1)
        self.assertIn("saved", comment.replies[0].lower())

    def test_reply_includes_note_id(self):
        comment = self._mod_comment("$note u/baduser first warning")
        with _patch_db(self.fake_db):
            from commands.note_command import process_note_command
            process_note_command(comment)
        self.assertIn("#1", comment.replies[0])

    def test_non_mod_cannot_add_note(self):
        comment = FakeComment("$note u/user123 some note", author_name="lender1", subreddit=self.plain_sub)
        with _patch_db(self.fake_db):
            from commands.note_command import process_note_command
            process_note_command(comment)
        self.assertIn("moderators", comment.replies[0].lower())

    def test_no_match_triggers_usage(self):
        comment = self._mod_comment("$note")
        with _patch_db(self.fake_db):
            from commands.note_command import process_note_command
            process_note_command(comment)
        self.assertIn("usage", comment.replies[0].lower())

    def test_missing_note_text_triggers_usage(self):
        comment = self._mod_comment("$note u/user123")
        with _patch_db(self.fake_db):
            from commands.note_command import process_note_command
            process_note_command(comment)
        self.assertIn("usage", comment.replies[0].lower())

    def test_not_in_body_no_reply(self):
        comment = self._mod_comment("just a regular comment")
        with _patch_db(self.fake_db):
            from commands.note_command import process_note_command
            process_note_command(comment)
        self.assertEqual(len(comment.replies), 0)


if __name__ == "__main__":
    unittest.main()
