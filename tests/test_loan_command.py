"""$loan makes an offer; only the borrower's $confirm records the loan.

Driven through main.py's dispatcher against a real database, like the other
end-to-end bot tests.
"""

from tests.support.dbcase import RealDBTestCase


class _Author:
    def __init__(self, name):
        self.name = name


class _Submission:
    def __init__(self, author, post_id="post1"):
        self.author = _Author(author) if author else None
        self.permalink = f"/r/loancentral/comments/{post_id}/x/"
        self.title = "[REQ] ($100)"


class _Comment:
    def __init__(self, body, author, submission, flair=None):
        self.body = body
        self.author = _Author(author)
        self.submission = submission
        self.subreddit = type("S", (), {"display_name": "loancentral"})()
        self.author_flair_text = flair
        self.replies = []

    def reply(self, text):
        self.replies.append(text)


class LoanOfferTests(RealDBTestCase):
    def setUp(self):
        super().setUp()
        import main
        self.main = main
        self.post = _Submission("borrower")

    def say(self, body, author, submission=None, flair=None):
        self.main.command_manager.recent_commands.clear()
        comment = _Comment(body, author, submission or self.post, flair=flair)
        self.main.command_manager.process_comment(comment)
        return comment

    def lend(self, body="$loan 100 USD", lender="lender"):
        return self.say(body, lender, flair="Verified Lender")

    def loans(self):
        return self.query("SELECT lender, borrower, amount, currency, repay_amount FROM loans")

    # -- $loan ----------------------------------------------------------------

    def test_loan_is_an_offer_not_a_loan(self):
        reply = self.lend().replies[0]
        self.assertEqual(self.loans(), [])
        self.assertIn("offering **100.00 USD** to u/borrower", reply)
        self.assertIn("$confirm", reply)

    def test_offer_goes_to_the_post_author_or_a_named_user(self):
        self.lend("$loan 50 USD u/someone")
        rows = self.query("SELECT borrower, amount FROM loan_offers ORDER BY id")
        self.assertEqual([(r[0], float(r[1])) for r in rows], [("someone", 50.0)])

    def test_no_flair_no_offer(self):
        comment = self.say("$loan 100 USD", "rando", flair=None)
        self.assertEqual(comment.replies, [])
        self.assertEqual(self.query("SELECT COUNT(*) FROM loan_offers")[0][0], 0)

    def test_repeating_the_same_loan_does_not_duplicate_the_offer(self):
        self.lend()
        self.lend()
        self.assertEqual(self.query("SELECT COUNT(*) FROM loan_offers")[0][0], 1)

    def test_cannot_offer_to_yourself(self):
        own = _Submission("lender")
        comment = self.say("$loan 100 USD", "lender", submission=own, flair="Verified Lender")
        self.assertIn("cannot lend to yourself", comment.replies[0])

    def test_zero_is_rejected(self):
        self.assertIn("greater than zero", self.lend("$loan 0 USD").replies[0])

    # -- $confirm -------------------------------------------------------------

    def test_confirm_records_the_loan_with_just_the_amount(self):
        self.lend()
        reply = self.say("$confirm", "borrower").replies[0]
        self.assertEqual([(r[0], r[1], float(r[2]), r[3], r[4]) for r in self.loans()],
                         [("lender", "borrower", 100.0, "USD", None)])
        self.assertIn("Confirmed", reply)
        self.assertIn("$paid_with_id", reply)

    def test_the_original_bots_confirm_format_still_works(self):
        self.lend()
        self.say("$confirm /u/lender 100.00 USD", "borrower")
        self.assertEqual(len(self.loans()), 1)

    def test_bang_confirm_works(self):
        self.lend()
        self.say("!confirm", "borrower")
        self.assertEqual(len(self.loans()), 1)

    def test_only_the_borrower_can_confirm(self):
        self.lend()
        reply = self.say("$confirm", "stranger").replies[0]
        self.assertIn("no loan offers", reply)
        self.assertEqual(self.loans(), [])

    def test_confirming_twice_makes_one_loan(self):
        self.lend()
        self.say("$confirm", "borrower")
        self.say("$confirm", "borrower")
        self.assertEqual(len(self.loans()), 1)

    def test_two_offers_need_the_lender_named(self):
        self.lend(lender="lender")
        self.make_user("lender2", role="lender", verified_lender=True)
        self.say("$loan 60 USD", "lender2", flair="Verified Lender")
        other_thread = _Submission("borrower", post_id="other")
        ambiguous = self.say("$confirm", "borrower", submission=other_thread).replies[0]
        self.assertIn("more than one offer", ambiguous)
        self.say("$confirm u/lender2", "borrower")
        self.assertEqual([r[0] for r in self.loans()], ["lender2"])

    def test_an_expired_offer_cannot_be_confirmed(self):
        self.lend()
        self.execute("UPDATE loan_offers SET expires_at = '2000-01-01 00:00:00'")
        self.say("$confirm", "borrower")
        self.assertEqual(self.loans(), [])

    def test_confirmed_loan_counts_in_both_records(self):
        self.lend("$loan 75 USD")
        self.say("$confirm", "borrower")
        stats = {r[0]: r[1:] for r in self.query(
            "SELECT username, loans_as_lender, loans_as_borrower FROM users")}
        self.assertEqual(stats["lender"][0], 1)
        self.assertEqual(stats["borrower"][1], 1)
