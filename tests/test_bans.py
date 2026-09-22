"""Phase 7 — global platform bans.

There was no ban system before this: no table, no check in any decorator, no
is_banned anywhere. "Ban" meant queueing a ban_user row for a moderator to
perform by hand on Reddit, which recorded an intention but never stopped the
account from using LoanCentral.

Enforcement is a single before_request hook rather than a check per route,
because forty per-route checks is exactly how the dispute bug happened.
"""

from decimal import Decimal

import services
from tests.support.dbcase import RealDBTestCase


class BanServiceTests(RealDBTestCase):

    def setUp(self):
        super().setUp()
        self.make_user("mod", role="mod")
        self.make_user("admin", role="admin")
        self.make_user("baddie", role="borrower")

    def test_ban_and_lookup(self):
        result, error = services.ban_user("baddie", "did not repay", "mod")
        self.assertIsNone(error)
        self.assertFalse(result["already_banned"])
        banned, details = services.is_user_banned("baddie")
        self.assertTrue(banned)
        self.assertEqual(details["reason"], "did not repay")
        self.assertEqual(details["banned_by"], "mod")

    def test_banning_twice_is_idempotent(self):
        services.ban_user("baddie", "first", "mod")
        result, error = services.ban_user("baddie", "second", "mod")
        self.assertIsNone(error)
        self.assertTrue(result["already_banned"])
        self.assertEqual(self.query("SELECT COUNT(*) FROM banned_users")[0][0], 1)

    def test_unban_lifts_the_ban(self):
        services.ban_user("baddie", "did not repay", "mod")
        result, error = services.unban_user("baddie", actor="mod", reason="appealed")
        self.assertIsNone(error)
        self.assertTrue(result["was_banned"])
        banned, _ = services.is_user_banned("baddie")
        self.assertFalse(banned)

    def test_unbanning_someone_who_is_not_banned_is_harmless(self):
        result, error = services.unban_user("baddie", actor="mod")
        self.assertIsNone(error)
        self.assertFalse(result["was_banned"])

    def test_ban_history_survives_an_unban(self):
        services.ban_user("baddie", "first offence", "mod")
        services.unban_user("baddie", actor="mod", reason="appealed")
        services.ban_user("baddie", "second offence", "mod")
        rows, error = services.list_banned_users(active_only=False)
        self.assertIsNone(error)
        self.assertEqual(len(rows), 2, "the earlier ban must remain on record")
        self.assertEqual(sum(1 for r in rows if r["active"]), 1)

    def test_cannot_ban_yourself(self):
        result, error = services.ban_user("mod", "oops", "mod")
        self.assertIsNone(result)
        self.assertIn("yourself", error)

    def test_a_mod_cannot_ban_another_mod(self):
        self.make_user("mod2", role="mod")
        result, error = services.ban_user("mod2", "disagreement", "mod", actor_role="mod")
        self.assertIsNone(result)
        self.assertIn("admin", error)
        banned, _ = services.is_user_banned("mod2")
        self.assertFalse(banned)

    def test_an_admin_can_ban_a_mod(self):
        self.make_user("mod2", role="mod")
        result, error = services.ban_user("mod2", "abuse", "admin", actor_role="admin")
        self.assertIsNone(error)
        self.assertTrue(services.is_user_banned("mod2")[0])

    def test_ban_writes_an_audit_row(self):
        services.ban_user("baddie", "did not repay", "mod")
        rows = self.query(
            "SELECT actor_username, target_id FROM audit_logs WHERE action_type = 'user_banned'")
        self.assertEqual(rows, [("mod", "baddie")])

    def test_unban_writes_an_audit_row(self):
        services.ban_user("baddie", "x", "mod")
        services.unban_user("baddie", actor="admin")
        rows = self.query(
            "SELECT actor_username FROM audit_logs WHERE action_type = 'user_unbanned'")
        self.assertEqual(rows, [("admin",)])

    def test_a_ban_follows_a_linked_reddit_account(self):
        """Banning the dashboard name must also stop the linked handle."""
        self.execute("UPDATE user_roles SET reddit_username = %s WHERE username = %s",
                     ("baddie_on_reddit", "baddie"))
        services.ban_user("baddie", "did not repay", "mod")
        self.assertTrue(services.is_user_banned("baddie_on_reddit")[0],
                        "the linked Reddit handle must be banned too")

    def test_listing_active_bans(self):
        services.ban_user("baddie", "x", "mod")
        self.make_user("other", role="borrower")
        services.ban_user("other", "y", "mod")
        services.unban_user("other", actor="mod")
        rows, error = services.list_banned_users(active_only=True)
        self.assertIsNone(error)
        self.assertEqual([r["username"] for r in rows], ["baddie"])


class BanEnforcementTests(RealDBTestCase):
    """A banned account is refused everywhere, in one hook."""

    def setUp(self):
        super().setUp()
        self.make_user("mod", role="mod")
        self.make_user("lender", role="lender", verified_lender=True)
        self.make_user("borrower", role="borrower")
        self.loan_id, error = services.create_loan(
            lender="lender", borrower="borrower", amount=Decimal("100.00"),
            currency="USD", thread_url="https://example.com/t",
            repay_amount=Decimal("120.00"), repay_date="2027-01-01")
        self.assertIsNone(error)

    def test_a_banned_lender_cannot_write(self):
        services.ban_user("lender", "abuse", "mod")
        self.login("lender", role="lender")
        response = self.client.post(f"/api/loans/{self.loan_id}/paid",
                                    json={"amount": "10.00", "currency": "USD"})
        self.assertEqual(response.status_code, 403)
        self.assertIn("banned", response.get_json()["error"].lower())
        status = self.query("SELECT status FROM loans WHERE loan_id = %s",
                            (self.loan_id,))[0][0]
        self.assertEqual(status, "confirmed")

    def test_a_banned_user_cannot_read_the_api_either(self):
        services.ban_user("borrower", "abuse", "mod")
        self.login("borrower", role="borrower")
        response = self.client.get("/api/users/me")
        self.assertEqual(response.status_code, 403)

    def test_the_ban_reason_is_returned(self):
        services.ban_user("borrower", "ghosted a lender", "mod")
        self.login("borrower", role="borrower")
        response = self.client.get("/api/users/me")
        self.assertEqual(response.get_json()["reason"], "ghosted a lender")

    def test_a_banned_user_can_still_sign_out(self):
        services.ban_user("borrower", "abuse", "mod")
        self.login("borrower", role="borrower")
        response = self.client.get("/auth/logout")
        self.assertIn(response.status_code, (200, 302))

    def test_an_unbanned_user_works_again(self):
        services.ban_user("lender", "abuse", "mod")
        services.unban_user("lender", actor="mod")
        self.login("lender", role="lender")
        response = self.client.post(f"/api/loans/{self.loan_id}/paid",
                                    json={"amount": "10.00", "currency": "USD"})
        self.assertEqual(response.status_code, 200, response.get_json())

    def test_unbanned_users_are_unaffected(self):
        self.login("lender", role="lender")
        response = self.client.post(f"/api/loans/{self.loan_id}/paid",
                                    json={"amount": "10.00", "currency": "USD"})
        self.assertEqual(response.status_code, 200, response.get_json())

    def test_a_ban_takes_effect_without_re_login(self):
        self.login("lender", role="lender")
        first = self.client.post(f"/api/loans/{self.loan_id}/paid",
                                 json={"amount": "10.00", "currency": "USD"})
        self.assertEqual(first.status_code, 200, first.get_json())
        services.ban_user("lender", "abuse", "mod")
        second = self.client.post(f"/api/loans/{self.loan_id}/paid",
                                  json={"amount": "10.00", "currency": "USD"})
        self.assertEqual(second.status_code, 403)


class BanRouteTests(RealDBTestCase):

    def setUp(self):
        super().setUp()
        self.make_user("mod", role="mod")
        self.make_user("admin", role="admin")
        self.make_user("baddie", role="borrower")
        self.make_user("lender", role="lender", verified_lender=True)

    def test_mod_can_ban_and_unban(self):
        self.login("mod", role="mod")
        response = self.client.post("/api/admin/bans/baddie",
                                    json={"reason": "did not repay"})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(services.is_user_banned("baddie")[0])

        response = self.client.delete("/api/admin/bans/baddie", json={"reason": "appeal"})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertFalse(services.is_user_banned("baddie")[0])

    def test_lender_cannot_ban(self):
        self.login("lender", role="lender")
        response = self.client.post("/api/admin/bans/baddie", json={"reason": "spite"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(services.is_user_banned("baddie")[0])

    def test_borrower_cannot_ban(self):
        self.login("baddie", role="borrower")
        response = self.client.post("/api/admin/bans/lender", json={"reason": "spite"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(services.is_user_banned("lender")[0])

    def test_anonymous_cannot_ban(self):
        self.logout()
        response = self.client.post("/api/admin/bans/baddie", json={"reason": "spite"})
        self.assertEqual(response.status_code, 403)

    def test_mod_banning_a_mod_is_refused_by_the_route(self):
        self.make_user("mod2", role="mod")
        self.login("mod", role="mod")
        response = self.client.post("/api/admin/bans/mod2", json={"reason": "x"})
        self.assertEqual(response.status_code, 403)

    def test_listing_bans(self):
        services.ban_user("baddie", "did not repay", "mod")
        self.login("mod", role="mod")
        response = self.client.get("/api/admin/bans")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["bans"][0]["username"], "baddie")

    def test_checking_one_user(self):
        services.ban_user("baddie", "did not repay", "mod")
        self.login("mod", role="mod")
        response = self.client.get("/api/admin/bans/baddie")
        self.assertTrue(response.get_json()["banned"])


class RedditSyncAdminRouteTests(RealDBTestCase):

    def setUp(self):
        super().setUp()
        self.make_user("mod", role="mod")
        self.make_user("lender", role="lender", verified_lender=True)

    def test_pending_view_is_read_only(self):
        self.login("mod", role="mod")
        response = self.client.get("/api/admin/reddit-sync/pending")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["live"],
                         "the admin view must never send to Reddit")

    def test_failures_view(self):
        self.login("mod", role="mod")
        response = self.client.get("/api/admin/reddit-sync/failures")
        self.assertEqual(response.status_code, 200)
        self.assertIn("failures", response.get_json())

    def test_lender_cannot_see_sync_health(self):
        self.login("lender", role="lender")
        for path in ("/api/admin/reddit-sync/pending",
                     "/api/admin/reddit-sync/failures"):
            self.assertEqual(self.client.get(path).status_code, 403, path)
