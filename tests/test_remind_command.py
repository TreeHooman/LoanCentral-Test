"""Tests for the $remind command."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.support.fakes import FakeComment, FakeDb, loan_record


def _patch_db(fake):
    return patch("services._get_db", side_effect=lambda: fake.connection())


def _run(body, fake_db, author="lender1"):
    comment = FakeComment(body, author_name=author)
    mock_reddit = MagicMock()
    with _patch_db(fake_db), \
         patch.dict("sys.modules", {"utils": MagicMock(
             reddit=mock_reddit,
             get_db_connection=lambda: fake_db.connection(),
         )}):
        from commands.remind_command import process_remind_command
        process_remind_command(comment)
    return comment, mock_reddit


class RemindCommandTests(unittest.TestCase):
    def setUp(self):
        self.loan = loan_record(
            db_id=1, public_id="L001", lender="lender1", borrower="borrower1",
            amount="100.00", amount_repaid="30.00", status="confirmed",
        )
        self.fake_db = FakeDb(loans=[self.loan])

    def test_sends_dm_to_borrower(self):
        comment, mock_reddit = _run("$remind L001", self.fake_db)
        mock_reddit.redditor.assert_called_with("borrower1")
        mock_reddit.redditor().message.assert_called_once()

    def test_reply_confirms_reminder_sent(self):
        comment, _ = _run("$remind L001", self.fake_db)
        self.assertEqual(len(comment.replies), 1)
        self.assertIn("reminder sent", comment.replies[0].lower())

    def test_reply_includes_loan_id(self):
        comment, _ = _run("$remind L001", self.fake_db)
        self.assertIn("L001", comment.replies[0])

    def test_reply_includes_outstanding_amount(self):
        comment, _ = _run("$remind L001", self.fake_db)
        # 100 - 30 = 70 outstanding
        self.assertIn("70.00", comment.replies[0])

    def test_custom_message_is_used(self):
        comment, mock_reddit = _run("$remind L001 please pay soon!", self.fake_db)
        call_kwargs = mock_reddit.redditor().message.call_args
        msg = call_kwargs[1].get("message") or call_kwargs[0][1]
        self.assertIn("please pay soon!", msg)

    def test_wrong_lender_cannot_remind(self):
        comment, mock_reddit = _run("$remind L001", self.fake_db, author="otherlender")
        self.assertEqual(len(comment.replies), 1)
        self.assertIn("could not find", comment.replies[0].lower())
        mock_reddit.redditor().message.assert_not_called()

    def test_repaid_loan_no_reminder(self):
        repaid = loan_record(
            db_id=2, public_id="L002", lender="lender1", borrower="borrower1",
            amount="50.00", amount_repaid="50.00", status="repaid",
        )
        db = FakeDb(loans=[repaid])
        comment, mock_reddit = _run("$remind L002", db)
        self.assertIn("already repaid", comment.replies[0].lower())
        mock_reddit.redditor().message.assert_not_called()

    def test_no_trigger_no_reply(self):
        comment, _ = _run("just chatting", self.fake_db)
        self.assertEqual(len(comment.replies), 0)

    def test_no_loan_id_shows_usage(self):
        comment, _ = _run("$remind", self.fake_db)
        self.assertIn("usage", comment.replies[0].lower())

    def test_dm_subject_includes_loan_id(self):
        comment, mock_reddit = _run("$remind L001", self.fake_db)
        call_kwargs = mock_reddit.redditor().message.call_args
        subject = call_kwargs[1].get("subject") or call_kwargs[0][0]
        self.assertIn("L001", subject)


if __name__ == "__main__":
    unittest.main()
