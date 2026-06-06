import importlib
import sys
import unittest
from unittest.mock import patch

from tests.support.fakes import FakeComment, FakeDb, FakeReddit, FakeSubmission, fake_utils_module


class ModsCommandTests(unittest.TestCase):
    def run_mods_command(self, body="$mods please review this"):
        fake_reddit = FakeReddit()
        subreddit = fake_reddit.subreddit("LoanCentralTest")
        submission = FakeSubmission(author_name="borrower", subreddit=subreddit, title="Test request title")
        comment = FakeComment(body=body, author_name="borrower", submission=submission, subreddit=subreddit)

        with patch.dict(sys.modules, {"utils": fake_utils_module(FakeDb(), reddit=fake_reddit)}):
            mods_command = importlib.import_module("commands.mods_command")
            mods_command.process_mods_command(comment)

        return comment, subreddit

    def test_mods_command_sends_modmail_and_replies(self):
        comment, subreddit = self.run_mods_command()

        self.assertEqual(len(subreddit.messages), 1)
        self.assertIn("Moderator Request from u/borrower", subreddit.messages[0]["subject"])
        self.assertIn("please review this", subreddit.messages[0]["message"])
        self.assertIn("notified the moderators", comment.replies[0])

    def test_non_mods_comment_gets_no_reply(self):
        comment, subreddit = self.run_mods_command(body="hello")

        self.assertEqual(subreddit.messages, [])
        self.assertEqual(comment.replies, [])


if __name__ == "__main__":
    unittest.main()

