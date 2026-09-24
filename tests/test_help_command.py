import importlib
import unittest

from tests.support.fakes import FakeComment


class HelpCommandTests(unittest.TestCase):
    def test_help_command_lists_core_commands(self):
        help_command = importlib.import_module("commands.help_command")
        comment = FakeComment(body="$help", author_name="borrower")

        help_command.process_help_command(comment)

        self.assertIn("$loan", comment.replies[0])
        self.assertIn("$paid_with_id", comment.replies[0])
        self.assertIn("$unpaid", comment.replies[0])
        self.assertIn("$refunded", comment.replies[0])
        # Brought back from the original bot, plus $login.
        for command in ("$confirm", "$stats", "$login"):
            self.assertIn(command, comment.replies[0])
        # Retired: borrowers can't mark their own loans repaid; $dispute and
        # $mods were removed (owner, 2026-09-24).
        for command in ("$repaid", "$dispute", "$mods"):
            self.assertNotIn(command, comment.replies[0])

    def test_non_help_comment_gets_no_reply(self):
        help_command = importlib.import_module("commands.help_command")
        comment = FakeComment(body="hello", author_name="borrower")

        help_command.process_help_command(comment)

        self.assertEqual(comment.replies, [])


if __name__ == "__main__":
    unittest.main()

