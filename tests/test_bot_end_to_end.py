"""The bot, driven through main.py itself, against a real database.

The per-command tests call each command module directly with fakes. These go
through the real entry points instead — main.handle_new_post for [REQ] posts
and main.CommandManager.process_comment for $commands — so they cover the
dispatch, the quote-stripping, the ban check and the comment-id capture that
sit between Reddit and the service layer.

Nothing here reaches Reddit: every post and comment is a local fake, and no
code path under test calls the shared client.
"""

from decimal import Decimal

# Deliberately no REDDIT_MODE override here: pytest imports every module before
# running any, so setting it at import time leaked into
# test_reddit_rate_limit and swapped the real PRAW client for the stub. Every
# Reddit object these tests touch is a local fake, so none is needed.
import services
from tests.support.dbcase import RealDBTestCase
from tests.support.fakes import FakeAuthor


class _Reply:
    def __init__(self, comment_id):
        self.id = comment_id


class FakePost:
    def __init__(self, post_id, title, author="borrower"):
        self.id = post_id
        self.title = title
        self.author = FakeAuthor(author)
        self.permalink = f"/r/loancentraltest/comments/{post_id}/x/"
        self.created_utc = 1_790_000_000
        self.replies = []

    def reply(self, body):
        self.replies.append(body)
        return _Reply(f"botreply_{self.id}")


class FakeCommandComment:
    def __init__(self, body, author):
        self.body = body
        self.author = FakeAuthor(author)
        self.replies = []
        self.subreddit = None

    def reply(self, body):
        self.replies.append(body)
        return _Reply("c_reply")


class BotEndToEndTests(RealDBTestCase):

    def setUp(self):
        super().setUp()
        import main
        self.main = main
        # A fresh cooldown table per test: the dispatcher rate-limits repeated
        # commands per user, which would otherwise leak between tests.
        self.main.command_manager.recent_commands.clear()
        self.make_user("lender", role="lender", verified_lender=True)
        self.make_user("borrower", role="borrower")

    def post(self, post_id, title, author="borrower"):
        post = FakePost(post_id, title, author)
        self.main.handle_new_post(post)
        return post

    def command(self, body, author):
        comment = FakeCommandComment(body, author)
        self.main.command_manager.process_comment(comment)
        return comment

    def request_row(self, post_id):
        rows = self.query(
            "SELECT request_id, request_status, reddit_comment_id FROM loan_requests "
            "WHERE reddit_post_id = %s", (post_id,))
        return rows[0] if rows else None

    # -- [REQ] posts --------------------------------------------------------

    def test_a_req_post_becomes_a_request_and_gets_one_reply(self):
        post = self.post("p1", "[REQ] ($150) (#Denver, CO, USA) (Repay $180) (2027-10-15)")
        row = self.request_row("p1")
        self.assertIsNotNone(row, "the post was not saved as a request")
        self.assertEqual(row[1], "open")
        self.assertEqual(len(post.replies), 1, "one reply per post keeps API use down")
        self.assertIn(row[0], post.replies[0])

    def test_the_bot_stores_its_own_comment_id(self):
        self.post("p2", "[REQ] ($150) (#Denver, CO, USA) (Repay $180) (2027-10-15)")
        self.assertEqual(self.request_row("p2")[2], "botreply_p2")

    def test_a_bare_dollar_post_is_saved(self):
        self.post("p3", "[REQ] $150 - Denver, CO, USA - Repay $180 by 10/15")
        self.assertIsNotNone(self.request_row("p3"))

    def test_a_pre_post_is_answered_but_creates_no_request(self):
        post = self.post("p4", "[PRE] ($150) (#Denver, CO, USA)")
        self.assertEqual(len(post.replies), 1)
        self.assertIsNone(self.request_row("p4"))

    def test_a_deleted_post_is_skipped(self):
        post = FakePost("p5", "[REQ] ($150) (Repay $180) (2027-10-15)")
        post.author = None
        self.main.handle_new_post(post)
        self.assertEqual(post.replies, [])
        self.assertIsNone(self.request_row("p5"))

    # -- $fund and the loan lifecycle --------------------------------------

    def _fund(self, post_id):
        self.post(post_id, "[REQ] ($150) (#Denver, CO, USA) (Repay $180) (2027-10-15)")
        request_id = self.request_row(post_id)[0]
        reply = self.command(f"$fund {request_id}", "lender")
        loan_id = self.query(
            "SELECT l.loan_id FROM loans l JOIN loan_requests r ON r.funded_loan_id = l.id "
            "WHERE r.request_id = %s", (request_id,))
        return request_id, (loan_id[0][0] if loan_id else None), reply

    def test_fund_command_creates_the_loan_and_queues_the_sync(self):
        request_id, loan_id, reply = self._fund("f1")
        self.assertIsNotNone(loan_id, reply.replies)
        self.assertEqual(self.request_row("f1")[1], "funded")
        queued = {row[0] for row in self.query(
            "SELECT action_type FROM reddit_actions WHERE request_id = %s", (request_id,))}
        self.assertEqual(queued, {"flair_sync", "funded_comment"})

    def test_fund_command_and_dashboard_produce_the_same_timeline(self):
        request_id, _, _ = self._fund("f2")
        events, _ = services.get_request_events(request_id)
        self.assertEqual([e["event_type"] for e in events], ["created", "funded"])

    def test_paid_command_repays_the_loan(self):
        _, loan_id, _ = self._fund("f3")
        self.command(f"$paid_with_id {loan_id} 150 USD", "lender")
        status = self.query("SELECT status FROM loans WHERE loan_id = %s", (loan_id,))[0][0]
        self.assertEqual(status, "repaid")

    def test_unpaid_command(self):
        _, loan_id, _ = self._fund("f4")
        self.command(f"$unpaid {loan_id}", "lender")
        status = self.query("SELECT status FROM loans WHERE loan_id = %s", (loan_id,))[0][0]
        self.assertEqual(status, "unpaid")

    def test_refunded_command(self):
        _, loan_id, _ = self._fund("f5")
        self.command(f"$refunded {loan_id}", "lender")
        status = self.query("SELECT status FROM loans WHERE loan_id = %s", (loan_id,))[0][0]
        self.assertEqual(status, "refunded")

    def test_repaid_loan_cannot_be_marked_unpaid_from_reddit_either(self):
        """Both interfaces go through the same lifecycle table."""
        _, loan_id, _ = self._fund("f6")
        self.command(f"$paid_with_id {loan_id} 150 USD", "lender")
        self.main.command_manager.recent_commands.clear()
        self.command(f"$unpaid {loan_id}", "lender")
        status = self.query("SELECT status FROM loans WHERE loan_id = %s", (loan_id,))[0][0]
        self.assertEqual(status, "repaid")

    def test_fund_records_just_the_amount(self):
        _, loan_id, _ = self._fund("f7")
        row = self.query("SELECT amount, currency, repay_amount, repay_date FROM loans "
                         "WHERE loan_id = %s", (loan_id,))[0]
        self.assertEqual((float(row[0]), row[1], row[2], row[3]), (150.0, "USD", None, None))

    def test_fund_with_an_amount_and_currency_overrides_the_request(self):
        self.post("f8", "[REQ] ($250) (#Denver, CO, USA) (Repay $300) (2027-10-15)")
        request_id = self.request_row("f8")[0]
        self.command(f"$fund {request_id} 300CAD", "lender")
        row = self.query(
            "SELECT l.amount, l.currency FROM loans l JOIN loan_requests r "
            "ON r.funded_loan_id = l.id WHERE r.request_id = %s", (request_id,))[0]
        self.assertEqual((float(row[0]), row[1]), (300.0, "CAD"))

    def test_a_flaired_lender_new_to_loancentral_can_fund(self):
        self.post("f9", "[REQ] ($150) (#Denver, CO, USA) (Repay $180) (2027-10-15)")
        request_id = self.request_row("f9")[0]
        comment = FakeCommandComment(f"$fund {request_id}", "brandnew")
        comment.author_flair_text = "Verified Lender"
        self.main.command_manager.process_comment(comment)
        self.assertEqual(self.request_row("f9")[1], "funded", comment.replies)

    # -- permissions --------------------------------------------------------

    def test_unverified_user_cannot_fund(self):
        self.make_user("rando", role="borrower")
        self.post("g1", "[REQ] ($150) (#Denver, CO, USA) (Repay $180) (2027-10-15)")
        request_id = self.request_row("g1")[0]
        self.command(f"$fund {request_id} 180 USD 2027-10-15", "rando")
        self.assertEqual(self.request_row("g1")[1], "open")

    def test_a_banned_lender_is_ignored(self):
        self.make_user("mod", role="mod")
        services.ban_user("lender", "test", "mod")
        self.post("g2", "[REQ] ($150) (#Denver, CO, USA) (Repay $180) (2027-10-15)")
        request_id = self.request_row("g2")[0]
        reply = self.command(f"$fund {request_id} 180 USD 2027-10-15", "lender")
        self.assertEqual(self.request_row("g2")[1], "open")
        self.assertEqual(reply.replies, [], "a banned user gets silence, not a reply")

    def test_quoted_commands_are_not_executed(self):
        self.post("g3", "[REQ] ($150) (#Denver, CO, USA) (Repay $180) (2027-10-15)")
        request_id = self.request_row("g3")[0]
        self.command(f"> $fund {request_id} 180 USD 2027-10-15", "lender")
        self.assertEqual(self.request_row("g3")[1], "open")

    def test_the_same_request_cannot_be_funded_twice_from_reddit(self):
        self.make_user("lender2", role="lender", verified_lender=True)
        request_id, _, _ = self._fund("g4")
        self.command(f"$fund {request_id} 180 USD 2027-10-15", "lender2")
        count = self.query(
            "SELECT COUNT(*) FROM loans WHERE lower(borrower) = 'borrower'")[0][0]
        self.assertEqual(count, 1)


class BotQueueDrainTests(RealDBTestCase):
    """After a command the bot may send queued Reddit updates straight away."""

    def setUp(self):
        super().setUp()
        import main
        self.main = main
        self.main.command_manager.recent_commands.clear()

    def run_drain(self, env_value):
        import os
        import reddit_sync
        from unittest.mock import patch
        calls = []

        def fake_run_once(**kwargs):
            calls.append(kwargs)
            return {"considered": 0, "sent": 0, "failed": 0, "skipped": 0, "unsupported": 0}, None

        with patch.dict(os.environ, {"REDDIT_SYNC_IN_BOT": env_value}), \
             patch.object(reddit_sync, "run_once", side_effect=fake_run_once):
            thread = self.main.drain_reddit_queue_soon()
            if thread is not None:
                thread.join(5)
        return calls

    def test_off_unless_switched_on(self):
        self.assertEqual(self.run_drain(""), [])
        self.assertEqual(self.run_drain("false"), [])

    def test_when_on_it_sends_live_with_the_bots_client(self):
        calls = self.run_drain("true")
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0]["live"])
        self.assertIs(calls[0]["reddit"], self.main.reddit)

    def test_a_pass_already_running_is_not_doubled(self):
        import os
        from unittest.mock import patch
        self.main._drain_running.acquire()
        try:
            with patch.dict(os.environ, {"REDDIT_SYNC_IN_BOT": "true"}):
                self.assertIsNone(self.main.drain_reddit_queue_soon())
        finally:
            self.main._drain_running.release()

    def test_a_command_triggers_a_drain(self):
        from unittest.mock import patch
        with patch.object(self.main, "drain_reddit_queue_soon") as drain:
            self.main.command_manager.process_comment(FakeCommandComment("$help", "borrower"))
        drain.assert_called_once()
