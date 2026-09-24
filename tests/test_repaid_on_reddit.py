"""A fully repaid loan shows as repaid on Reddit, however it was repaid.

$paid_with_id, the dashboard Paid button and bulk paid all go through
services.mark_repaid, which queues a REPAID flair change and a "Repaid" message
for the loan's post. These run the bot and the dashboard against a real
database, then drain the queue into a fake Reddit and check what it ended up
showing.
"""

import reddit_sync
import services
from tests.support.dbcase import RealDBTestCase
from tests.test_bot_end_to_end import FakeCommandComment, FakePost


class _FakeRedditComment:
    def __init__(self, store, comment_id):
        self._store, self.id = store, comment_id

    @property
    def body(self):
        return self._store.comments.get(self.id, "")

    def edit(self, body):
        self._store.comments[self.id] = body


class _FakeSubmission:
    def __init__(self, store, post_id):
        self._store, self.id = store, post_id
        store_ref = store

        class _Mod:
            def flair(self, text=None):
                store_ref.flair[post_id] = text

        self.mod = _Mod()

    def reply(self, body):
        self._store.post_replies.setdefault(self.id, []).append(body)


class FakeReddit:
    def __init__(self):
        self.flair, self.comments, self.post_replies = {}, {}, {}

    def submission(self, id):
        return _FakeSubmission(self, id)

    def comment(self, id):
        return _FakeRedditComment(self, id)


class RepaidOnRedditTests(RealDBTestCase):
    def setUp(self):
        super().setUp()
        import main
        self.main = main
        self.main.command_manager.recent_commands.clear()
        self.make_user("lender", role="lender", verified_lender=True)
        self.make_user("borrower", role="borrower")
        self.reddit = FakeReddit()

    def fund(self, post_id):
        post = FakePost(post_id, "[REQ] ($150) (#Denver, CO, USA) (Repay $180) (2027-10-15)")
        self.main.handle_new_post(post)
        request_id = self.query("SELECT request_id FROM loan_requests WHERE reddit_post_id = %s",
                                (post_id,))[0][0]
        # The bot's reply on the post, as Reddit would hold it.
        self.reddit.comments[f"botreply_{post_id}"] = post.replies[0]
        self.command(f"$fund {request_id}")
        return self.query(
            "SELECT l.loan_id FROM loans l JOIN loan_requests r ON r.funded_loan_id = l.id "
            "WHERE r.request_id = %s", (request_id,))[0][0]

    def command(self, body):
        self.main.command_manager.recent_commands.clear()
        comment = FakeCommandComment(body, "lender")
        self.main.command_manager.process_comment(comment)
        return comment

    def queued(self, loan_id):
        return [(row[0], row[1]) for row in self.query(
            "SELECT action_type, status FROM reddit_actions WHERE loan_id = %s ORDER BY id",
            (loan_id,))]

    def drain(self):
        summary, error = reddit_sync.run_once(limit=50, live=True, reddit=self.reddit)
        self.assertIsNone(error)
        return summary

    # -- queueing -------------------------------------------------------------

    def test_paid_command_in_full_queues_repaid_flair_and_message(self):
        loan_id = self.fund("r1")
        self.command(f"$paid_with_id {loan_id} 150 USD")
        self.assertEqual([a for a, _ in self.queued(loan_id)],
                         ["flair_sync", "funded_comment", "flair_sync", "repaid_comment"])

    def test_the_dashboard_paid_button_queues_the_same(self):
        loan_id = self.fund("r2")
        self.login("lender", role="lender")
        response = self.client.post(f"/api/loans/{loan_id}/paid",
                                    json={"amount": "150", "currency": "USD"})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertIn(("repaid_comment", "queued"), self.queued(loan_id))

    def test_a_partial_payment_queues_nothing(self):
        loan_id = self.fund("r3")
        self.command(f"$paid_with_id {loan_id} 50 USD")
        self.assertNotIn("repaid_comment", [a for a, _ in self.queued(loan_id)])

    # -- what Reddit ends up showing -------------------------------------------

    def test_reddit_ends_up_repaid_even_when_funded_was_still_waiting(self):
        loan_id = self.fund("r4")
        self.command(f"$paid_with_id {loan_id} 150 USD")
        self.drain()
        self.assertEqual(self.reddit.flair["r4"], services.REPAID_FLAIR_TEXT)
        body = self.reddit.comments["botreply_r4"]
        self.assertIn("Funded by u/lender", body)
        self.assertIn("Repaid", body)
        self.assertLess(body.index("Funded by"), body.index("Repaid"))

    def test_a_retried_funded_flair_does_not_overwrite_repaid(self):
        loan_id = self.fund("r5")
        self.drain()
        self.command(f"$paid_with_id {loan_id} 150 USD")
        self.drain()
        # Simulate the FUNDED change failing earlier and coming round again.
        self.execute("UPDATE reddit_actions SET status = 'queued', next_attempt_at = NULL "
                     "WHERE loan_id = %s AND action_type = 'flair_sync' "
                     "AND payload LIKE %s", (loan_id, "%FUNDED%"))
        self.drain()
        self.assertEqual(self.reddit.flair["r5"], services.REPAID_FLAIR_TEXT)

    def test_a_loan_recorded_with_loan_command_gets_a_reply_on_its_post(self):
        comment = FakeCommandComment("$loan 100 USD u/borrower", "lender")
        comment.submission = FakePost("abc123", "[REQ] ($100)")
        self.main.command_manager.process_comment(comment)
        loan_id = self.query("SELECT loan_id FROM loans WHERE amount = 100")[0][0]
        self.command(f"$paid_with_id {loan_id} 100 USD")
        self.drain()
        self.assertEqual(self.reddit.flair.get("abc123"), services.REPAID_FLAIR_TEXT)
        self.assertIn("Repaid", self.reddit.post_replies["abc123"][0])
