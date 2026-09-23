"""Phase 5 — Reddit synchronisation.

The rule these tests exist to protect: the database is authoritative. Funding
commits first and queues the Reddit side afterwards, so no Reddit failure —
outage, lost permission, deleted post — may change loan state.

A fake Reddit client stands in for PRAW. Nothing here touches the network, and
run_once() is dry-run unless a test explicitly passes live=True.
"""

import unittest
from datetime import datetime
from decimal import Decimal

import reddit_sync
import services
from tests.support.dbcase import RealDBTestCase


class FakeComment:
    def __init__(self, comment_id="c1", body="original bot comment"):
        self.id = comment_id
        self.body = body
        self.edits = []

    def edit(self, body):
        self.edits.append(body)
        self.body = body


class FakeModeration:
    def __init__(self, submission):
        self._submission = submission

    def flair(self, text=None, **kwargs):
        if self._submission.raises:
            raise self._submission.raises
        self._submission.flair_text = text


class FakeSubmission:
    def __init__(self, submission_id="p1", raises=None):
        self.id = submission_id
        self.flair_text = None
        self.raises = raises
        self.replies = []
        self.mod = FakeModeration(self)

    def reply(self, body):
        if self.raises:
            raise self.raises
        comment = FakeComment("new", body)
        self.replies.append(comment)
        return comment


class FakeReddit:
    def __init__(self, submission=None, comment=None):
        self._submission = submission or FakeSubmission()
        self._comment = comment

    def submission(self, id=None):
        return self._submission

    def comment(self, id=None):
        if self._comment is None:
            raise RuntimeError("Comment not found")
        return self._comment


class FundingQueuesRedditWorkTests(RealDBTestCase):

    TITLE = "[REQ] ($150) (#Austin, TX, USA) (Repay $180) (2027-08-01)"

    def setUp(self):
        super().setUp()
        self.make_user("lender", role="lender", verified_lender=True)
        self.request_id, error = services.save_loan_request(
            "borrower", self.TITLE, "https://example.com/p", datetime.now(), "post1")
        self.assertIsNone(error)
        self.execute(
            "UPDATE loan_requests SET reddit_comment_id = %s WHERE request_id = %s",
            ("botc1", self.request_id))

    def queued(self):
        return {row[0]: row[1] for row in self.query(
            "SELECT action_type, status FROM reddit_actions")}

    def test_funding_queues_flair_and_comment(self):
        loan_id, error = services.fund_loan_request(
            self.request_id, "lender", 180.0, "2027-08-01")
        self.assertIsNone(error, error)
        self.assertEqual(self.queued(),
                         {"flair_sync": "queued", "funded_comment": "queued"})

    def test_queued_comment_names_the_lender(self):
        loan_id, _ = services.fund_loan_request(
            self.request_id, "lender", 180.0, "2027-08-01")
        payload = self.query(
            "SELECT payload FROM reddit_actions WHERE action_type = 'funded_comment'")[0][0]
        self.assertIn("Funded by u/lender", payload)
        self.assertIn(loan_id, payload)

    def test_nothing_is_queued_without_a_reddit_post(self):
        """Dashboard-only loans have no post to synchronise."""
        request_id, _ = services.create_loan_request(
            borrower_username="borrower2", requested_amount=Decimal("50.00"))
        services.fund_loan_request(request_id, "lender", 60.0, "2027-08-01")
        self.assertEqual(self.query("SELECT COUNT(*) FROM reddit_actions")[0][0], 0)

    def test_queueing_is_deduped(self):
        services.fund_loan_request(self.request_id, "lender", 180.0, "2027-08-01")
        loan_id = self.query(
            "SELECT loan_id FROM loans")[0][0]
        services.queue_request_funded_sync(
            request_id=self.request_id, loan_id=loan_id, lender="lender",
            reddit_post_id="post1", reddit_comment_id="botc1")
        self.assertEqual(self.query("SELECT COUNT(*) FROM reddit_actions")[0][0], 2)

    def test_a_queueing_failure_does_not_fail_the_loan(self):
        """The loan is committed before anything is queued."""
        original = services.enqueue_reddit_action
        services.enqueue_reddit_action = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("queue is down"))
        try:
            loan_id, error = services.fund_loan_request(
                self.request_id, "lender", 180.0, "2027-08-01")
        finally:
            services.enqueue_reddit_action = original
        self.assertIsNone(error, "a queue failure must not surface as a funding error")
        self.assertEqual(self.query("SELECT COUNT(*) FROM loans")[0][0], 1)
        status = self.query(
            "SELECT request_status FROM loan_requests WHERE request_id = %s",
            (self.request_id,))[0][0]
        self.assertEqual(status, "funded")


class WorkerTests(RealDBTestCase):

    TITLE = "[REQ] ($150) (#Austin, TX, USA) (Repay $180) (2027-08-01)"

    def setUp(self):
        super().setUp()
        self.make_user("lender", role="lender", verified_lender=True)
        self.request_id, _ = services.save_loan_request(
            "borrower", self.TITLE, "https://example.com/p", datetime.now(), "post1")
        self.execute(
            "UPDATE loan_requests SET reddit_comment_id = %s WHERE request_id = %s",
            ("botc1", self.request_id))
        self.loan_id, error = services.fund_loan_request(
            self.request_id, "lender", 180.0, "2027-08-01")
        self.assertIsNone(error, error)

    def statuses(self):
        return {row[0]: row[1] for row in self.query(
            "SELECT action_type, status FROM reddit_actions")}

    def loan_status(self):
        return self.query("SELECT status FROM loans WHERE loan_id = %s",
                          (self.loan_id,))[0][0]

    # -- dry run ------------------------------------------------------------

    def test_dry_run_sends_nothing_and_records_nothing(self):
        summary, error = reddit_sync.run_once()
        self.assertIsNone(error)
        self.assertFalse(summary["live"])
        self.assertEqual(summary["considered"], 2)
        self.assertEqual(summary["sent"], 0)
        self.assertEqual(set(self.statuses().values()), {"queued"})

    # -- success ------------------------------------------------------------

    def test_live_pass_sets_flair_and_edits_the_bot_comment(self):
        submission = FakeSubmission("post1")
        comment = FakeComment("botc1")
        reddit = FakeReddit(submission, comment)

        summary, error = reddit_sync.run_once(live=True, reddit=reddit)
        self.assertIsNone(error)
        self.assertEqual(summary["sent"], 2, summary)
        self.assertEqual(submission.flair_text, reddit_sync_flair())
        self.assertIn("Funded by u/lender", comment.body)
        self.assertEqual(set(self.statuses().values()), {"sent"})

    def test_a_second_pass_does_not_comment_twice(self):
        submission = FakeSubmission("post1")
        comment = FakeComment("botc1")
        reddit = FakeReddit(submission, comment)
        reddit_sync.run_once(live=True, reddit=reddit)
        edits_after_first = len(comment.edits)

        summary, _ = reddit_sync.run_once(live=True, reddit=reddit)
        self.assertEqual(summary["considered"], 0,
                         "sent actions must not be picked up again")
        self.assertEqual(len(comment.edits), edits_after_first)

    def test_reapplying_an_already_synced_comment_is_a_no_op(self):
        comment = FakeComment("botc1")
        reddit = FakeReddit(FakeSubmission("post1"), comment)
        reddit_sync.run_once(live=True, reddit=reddit)

        # Re-queue the same work and run again: the body is already present.
        self.execute("UPDATE reddit_actions SET status = 'queued', "
                     "next_attempt_at = NULL WHERE action_type = 'funded_comment'")
        reddit_sync.run_once(live=True, reddit=reddit)
        self.assertEqual(comment.body.count("Funded by u/lender"), 1)

    # -- failure ------------------------------------------------------------

    def test_a_transient_failure_is_retried_with_backoff(self):
        reddit = FakeReddit(FakeSubmission("post1", raises=RuntimeError("503 server busy")),
                            FakeComment("botc1"))
        summary, _ = reddit_sync.run_once(live=True, reddit=reddit)
        self.assertEqual(summary["failed"], 1, summary)

        row = self.query(
            "SELECT status, attempts, last_error, next_attempt_at FROM reddit_actions "
            "WHERE action_type = 'flair_sync'")[0]
        self.assertEqual(row[0], "queued")
        self.assertEqual(row[1], 1)
        self.assertIn("503", row[2])
        self.assertIsNotNone(row[3], "a retry time must be scheduled")

    def test_backoff_holds_the_action_back_on_the_next_pass(self):
        reddit = FakeReddit(FakeSubmission("post1", raises=RuntimeError("503 server busy")),
                            FakeComment("botc1"))
        reddit_sync.run_once(live=True, reddit=reddit)
        summary, _ = reddit_sync.run_once(live=True, reddit=reddit)
        self.assertEqual(summary["considered"], 0,
                         "the failed action is not due again yet")

    def test_repeated_failures_end_as_failed(self):
        reddit = FakeReddit(FakeSubmission("post1", raises=RuntimeError("503 server busy")),
                            FakeComment("botc1"))
        for _ in range(reddit_sync.MAX_ATTEMPTS):
            self.execute("UPDATE reddit_actions SET next_attempt_at = NULL "
                         "WHERE action_type = 'flair_sync'")
            reddit_sync.run_once(live=True, reddit=reddit)
        self.assertEqual(self.statuses()["flair_sync"], "failed")

    def test_a_deleted_post_is_skipped_not_retried_forever(self):
        reddit = FakeReddit(FakeSubmission("post1", raises=RuntimeError("404 not found")),
                            FakeComment("botc1"))
        summary, _ = reddit_sync.run_once(live=True, reddit=reddit)
        self.assertEqual(summary["skipped"], 1, summary)
        row = self.query("SELECT status, next_attempt_at FROM reddit_actions "
                         "WHERE action_type = 'flair_sync'")[0]
        self.assertEqual(row[0], "skipped")
        self.assertIsNone(row[1], "a gone post must not be rescheduled")

    def test_losing_the_flair_permission_does_not_touch_the_loan(self):
        reddit = FakeReddit(FakeSubmission("post1", raises=RuntimeError("403 Forbidden")),
                            FakeComment("botc1"))
        reddit_sync.run_once(live=True, reddit=reddit)
        self.assertEqual(self.loan_status(), "confirmed")
        self.assertEqual(self.query("SELECT COUNT(*) FROM loans")[0][0], 1)

    def test_total_reddit_failure_leaves_the_loan_funded(self):
        class ExplodingReddit:
            def submission(self, id=None):
                raise RuntimeError("network unreachable")

            def comment(self, id=None):
                raise RuntimeError("network unreachable")

        reddit_sync.run_once(live=True, reddit=ExplodingReddit())
        self.assertEqual(self.loan_status(), "confirmed")
        status = self.query(
            "SELECT request_status FROM loan_requests WHERE request_id = %s",
            (self.request_id,))[0][0]
        self.assertEqual(status, "funded",
                         "the database is authoritative regardless of Reddit")

    def test_failures_are_reported_for_review(self):
        reddit = FakeReddit(FakeSubmission("post1", raises=RuntimeError("404 not found")),
                            FakeComment("botc1"))
        reddit_sync.run_once(live=True, reddit=reddit)
        rows, error = reddit_sync.sync_failures()
        self.assertIsNone(error)
        self.assertTrue(any(r["action_type"] == "flair_sync" for r in rows))

    def test_unsupported_action_types_are_left_for_a_human(self):
        services.enqueue_reddit_action(
            "ban_user", target_user="someone", reason="test", created_by="mod")
        self.execute("UPDATE reddit_actions SET status = 'queued', next_attempt_at = NULL")
        summary, _ = reddit_sync.run_once(
            live=True, reddit=FakeReddit(FakeSubmission("post1"), FakeComment("botc1")))
        self.assertEqual(summary["unsupported"], 1, summary)
        self.assertEqual(self.statuses()["ban_user"], "queued")


class CommentBodyTests(RealDBTestCase):

    def test_body_names_the_lender_and_disclaims_involvement(self):
        body = services.funded_comment_body("alice", "LN-123")
        self.assertIn("Funded by u/alice", body)
        self.assertIn("LN-123", body)
        self.assertIn("not a party", body)


def reddit_sync_flair():
    return services.FUNDED_FLAIR_TEXT


class LiveLockTests(unittest.TestCase):
    """Two live passes at once would send the same comment twice."""

    def _fake_conn(self, acquired):
        from unittest.mock import MagicMock
        conn = MagicMock()
        conn.is_sqlite = False
        conn.cursor.return_value.fetchone.return_value = (acquired,)
        return conn

    def test_live_pass_is_skipped_while_another_holds_the_lock(self):
        from unittest.mock import MagicMock, patch
        conn = self._fake_conn(False)
        reddit = MagicMock()
        with patch("services._get_db", return_value=conn), \
             patch.object(reddit_sync, "due_actions", side_effect=AssertionError("queue read")):
            summary, error = reddit_sync.run_once(live=True, reddit=reddit)
        self.assertIsNone(summary)
        self.assertIn("already running", error)
        reddit.assert_not_called()
        conn.close.assert_called_once()

    def test_dry_run_never_takes_the_lock(self):
        from unittest.mock import patch
        with patch.object(reddit_sync, "_acquire_live_lock", side_effect=AssertionError("locked")), \
             patch.object(reddit_sync, "due_actions", return_value=([], None)):
            summary, error = reddit_sync.run_once()
        self.assertIsNone(error)
        self.assertEqual(summary["considered"], 0)
