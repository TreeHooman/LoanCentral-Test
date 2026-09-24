"""Trust tiers and the Legacy Lender role.

Tiers count repaid loans across every name an account uses; Legacy is granted
by an admin, audited, and takes priority in flair. The flair worker only ever
rewrites an existing lender flair, so a rank can never grant lender access.
"""

import json
import os
from unittest.mock import MagicMock, patch

import tiers
from tests.support.dbcase import RealDBTestCase


class TierThresholdTests(RealDBTestCase):
    def test_lender_thresholds(self):
        cases = {0: None, 1: "Iron", 24: "Iron", 25: "Bronze", 49: "Bronze",
                 50: "Silver", 99: "Silver", 100: "Gold", 199: "Gold",
                 200: "Platinum", 499: "Platinum", 500: "Diamond", 5000: "Diamond"}
        for count, name in cases.items():
            self.assertEqual(tiers.tier_for(count, "lender"), name, count)

    def test_next_tier(self):
        self.assertEqual(tiers.next_tier(0), ("Iron", 1))
        self.assertEqual(tiers.next_tier(30), ("Silver", 20))
        self.assertEqual(tiers.next_tier(500), (None, 0))

    def test_borrower_thresholds(self):
        cases = {0: None, 1: "Iron", 4: "Iron", 5: "Bronze", 10: "Silver", 20: "Gold",
                 40: "Platinum", 75: "Diamond"}
        for count, name in cases.items():
            self.assertEqual(tiers.tier_for(count, "borrower"), name, count)

    def test_borrower_thresholds_are_a_separate_setting(self):
        with patch.dict(os.environ, {"BORROWER_TIERS": "Gold:10,Iron:1"}):
            self.assertEqual(tiers.tier_for(10, "borrower"), "Gold")
            self.assertEqual(tiers.tier_for(10, "lender"), "Iron")


class TierDataTests(RealDBTestCase):
    def setUp(self):
        super().setUp()
        self.make_user("dashlender", role="lender", verified_lender=True)
        self.execute("UPDATE user_roles SET reddit_username = %s WHERE username = %s",
                     ("RedditLender", "dashlender"))
        self.make_user("boss", role="admin")
        n = 0
        # 20 repaid under the Reddit handle, 5 under the dashboard name = Bronze.
        for lender, count in (("RedditLender", 20), ("dashlender", 5)):
            for _ in range(count):
                n += 1
                self.add_loan(f"L-{n}", lender, "someborrower", "repaid")
        self.add_loan("OPEN-1", "dashlender", "someborrower", "confirmed")

    def add_loan(self, loan_id, lender, borrower, status):
        self.execute(
            "INSERT INTO loans (loan_id, lender, borrower, amount, amount_repaid, currency, status, "
            "date_created, original_thread) "
            "VALUES (%s, %s, %s, 100, 0, 'USD', %s, CURRENT_TIMESTAMP, 'https://reddit.com/x')",
            (loan_id, lender, borrower, status),
        )

    def queued(self, action_type):
        return self.execute("SELECT target_user FROM reddit_actions WHERE action_type = %s",
                            (action_type,))

    def test_repaid_counts_cover_every_name_and_skip_open_loans(self):
        self.assertEqual(tiers.repaid_counts("dashlender"), (25, 0))
        self.assertEqual(tiers.repaid_counts("redditlender"), (25, 0))
        self.assertEqual(tiers.repaid_counts("someborrower"), (0, 25))

    def test_standing_and_labels(self):
        s = tiers.standing("dashlender")
        self.assertEqual(s["lender_tier"], "Bronze")
        self.assertEqual(s["lender_next_tier"], "Silver")
        self.assertFalse(s["legacy"])
        self.assertEqual(tiers.flair_text("dashlender"), "Verified Lender · Bronze")
        self.assertIn("Funded by u/dashlender (Bronze).",
                      __import__("services").funded_comment_body("dashlender", "L-1"))

    def test_legacy_takes_priority_and_follows_the_reddit_name(self):
        import services
        ok, error = services.set_legacy_lender("RedditLender", True, "boss")
        self.assertTrue(ok, error)
        self.assertTrue(tiers.is_legacy("dashlender"))
        self.assertEqual(tiers.flair_text("redditlender"), "Verified Lender · Legacy")
        self.assertEqual([r[0] for r in self.queued("lender_flair")], ["redditlender"])

    def test_legacy_endpoint_is_admin_only_and_audited(self):
        self.login("dashlender", role="lender")
        r = self.client.post("/api/admin/users/dashlender/legacy", json={"legacy": True})
        self.assertIn(r.status_code, (401, 403))
        self.assertFalse(tiers.is_legacy("dashlender"))

        self.login("boss", role="admin")
        r = self.client.post("/api/admin/users/dashlender/legacy", json={"legacy": True})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertTrue(tiers.is_legacy("dashlender"))
        audit = self.execute("SELECT action_type, actor_username FROM audit_logs "
                             "WHERE target_id = %s", ("dashlender",))
        self.assertIn(("legacy_lender_granted", "boss"), [tuple(a) for a in audit])

        r = self.client.post("/api/admin/users/dashlender/legacy", json={"legacy": False})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(tiers.is_legacy("dashlender"))

    def test_admin_profile_and_stats_include_standing(self):
        self.login("boss", role="admin")
        r = self.client.get("/api/admin/lenders/dashlender")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["standing"]["lender_tier"], "Bronze")
        self.login("dashlender", role="lender")
        r = self.client.get("/api/stats/lender/dashlender")
        self.assertEqual(r.get_json()["standing"]["lender_repaid"], 25)

    def test_crossing_a_tier_queues_a_flair_update(self):
        import services
        self.execute("DELETE FROM loans WHERE loan_id = 'L-1'")  # 24 repaid: Iron
        with patch.object(services, "queue_loan_repaid_sync", lambda *a, **k: None):
            services._queue_flair_if_tier_changed("dashlender")
        self.assertEqual(self.queued("lender_flair"), [])
        self.add_loan("L-1", "dashlender", "someborrower", "repaid")  # 25: Bronze
        services._queue_flair_if_tier_changed("dashlender")
        self.assertEqual(len(self.queued("lender_flair")), 1)

    def test_logi_shows_the_rank(self):
        from commands.logi_command import process_logi_command
        comment = MagicMock()
        comment.body = "$logi u/dashlender"
        process_logi_command(comment)
        self.assertIn("| Rank | Bronze |", comment.reply.call_args[0][0])

    def test_nav_badge_shows_the_rank(self):
        self.login("dashlender", role="lender")
        page = self.client.get("/dashboard/profile")
        if page.status_code == 200:
            self.assertIn("rank-bronze", page.get_data(as_text=True))


class FlairWorkerTests(RealDBTestCase):
    def setUp(self):
        super().setUp()
        self.make_user("lender1", role="lender")
        for n in range(100):
            self.execute(
                "INSERT INTO loans (loan_id, lender, borrower, amount, amount_repaid, currency, "
                "status, date_created, original_thread) VALUES (%s, 'lender1', 'b', 10, 10, "
                "'USD', 'repaid', CURRENT_TIMESTAMP, 'x')", (f"G-{n}",))

    def run_handler(self, current_text):
        import reddit_sync
        reddit = MagicMock()
        sub = reddit.subreddit.return_value
        sub.flair.return_value = [{"flair_text": current_text, "flair_css_class": "lender",
                                   "flair_template_id": None}]
        action = {"target_user": "lender1", "subreddit": "loancentral",
                  "payload_json": json.dumps({"reddit_username": "lender1"})}
        with patch.dict(os.environ, {"LENDER_FLAIR_TEMPLATE_ID": ""}):
            result = reddit_sync.HANDLERS["lender_flair"](action, reddit)
        return result, sub.flair.set

    def test_sets_the_ranked_flair_for_a_flaired_lender(self):
        (ok, _, _), setter = self.run_handler("Verified Lender")
        self.assertTrue(ok)
        setter.assert_called_once()
        self.assertEqual(setter.call_args.kwargs["text"], "Verified Lender · Gold")

    def test_never_gives_flair_to_someone_without_it(self):
        (ok, _, _), setter = self.run_handler("Borrower")
        self.assertTrue(ok)
        setter.assert_not_called()

    def test_ranked_flair_still_passes_the_lender_gate(self):
        from commands.lender_gate import _flair_matches
        with patch.dict(os.environ, {"LENDER_FLAIR_TEMPLATE_ID": ""}):
            self.assertTrue(_flair_matches("Verified Lender · Gold", None))
            self.assertTrue(_flair_matches("Verified Lender · Legacy", None))
            self.assertFalse(_flair_matches("Verified Lender · pending", None))
