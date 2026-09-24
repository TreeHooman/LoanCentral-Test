"""Admins create login keys for Reddit names, linking the account as they go."""

from tests.support.dbcase import RealDBTestCase


class AdminKeyTests(RealDBTestCase):
    def setUp(self):
        super().setUp()
        self.make_user("boss", role="admin")
        self.login("boss", role="admin")

    def create(self, **body):
        return self.client.post("/api/admin/keys", json=body)

    def roles_row(self, username):
        rows = self.query("SELECT role, reddit_username FROM user_roles WHERE username = %s",
                          (username,))
        return rows[0] if rows else None

    def key_count(self, username):
        return self.query("SELECT COUNT(*) FROM lender_keys WHERE username = %s", (username,))[0][0]

    def test_a_key_for_a_reddit_name_creates_a_linked_lender_account(self):
        response = self.create(reddit_username="u/UltraLender")
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        self.assertTrue(body["key"].startswith("LC-"))
        self.assertEqual(body["username"], "ultralender")
        # The old lstrip("u/") turned this into "ltralender".
        self.assertEqual(self.roles_row("ultralender"), ("lender", "ultralender"))

    def test_the_dashboard_username_can_differ_from_the_reddit_name(self):
        self.create(reddit_username="RedditOne", username="dash1")
        self.assertEqual(self.roles_row("dash1"), ("lender", "redditone"))

    def test_a_key_does_not_demote_a_mod_or_admin(self):
        self.make_user("amod", role="mod")
        self.create(reddit_username="amod")
        self.create(reddit_username="boss")
        self.assertEqual(self.roles_row("amod")[0], "mod")
        self.assertEqual(self.roles_row("boss")[0], "admin")

    def test_a_reddit_name_linked_elsewhere_is_refused_and_no_key_made(self):
        self.create(reddit_username="shared", username="first")
        response = self.create(reddit_username="shared", username="second")
        self.assertEqual(response.status_code, 400)
        self.assertIn("already linked", response.get_json()["error"])
        self.assertEqual(self.key_count("second"), 0)

    def test_a_reddit_name_that_is_another_account_is_refused(self):
        self.make_user("existing", role="lender")
        response = self.create(reddit_username="existing", username="someoneelse")
        self.assertEqual(response.status_code, 400)
        self.assertIn("separate dashboard account", response.get_json()["error"])

    def test_creating_and_revoking_are_audited(self):
        self.create(reddit_username="audited")
        key_id = self.query("SELECT id FROM lender_keys WHERE username = 'audited'")[0][0]
        self.client.post(f"/api/admin/keys/{key_id}/revoke")
        actions = {r[0] for r in self.query("SELECT action_type FROM audit_logs")}
        self.assertTrue({"lender_key_created", "reddit_username_linked",
                         "lender_key_revoked"} <= actions, actions)

    def test_the_key_list_shows_the_linked_reddit_name(self):
        self.create(reddit_username="RedditOne", username="dash1")
        keys = self.client.get("/api/admin/keys").get_json()
        self.assertEqual(keys[0]["reddit_username"], "redditone")

    def test_non_admins_cannot_create_keys(self):
        self.make_user("lender1", role="lender", verified_lender=True)
        self.login("lender1", role="lender")
        response = self.create(reddit_username="x")
        self.assertIn(response.status_code, (302, 401, 403))
        self.assertEqual(self.key_count("x"), 0)

    def test_the_lender_signs_in_and_sees_loans_the_bot_recorded(self):
        self.execute(
            "INSERT INTO loans (loan_id, lender, borrower, amount, amount_repaid, currency, status, "
            "date_created, original_thread) VALUES ('B-9', 'RedditOne', 'b1', 75, 0, 'USD', "
            "'confirmed', CURRENT_TIMESTAMP, 'https://reddit.com/x')")
        key = self.create(reddit_username="RedditOne", username="dash1").get_json()["key"]
        self.logout()
        signin = self.client.post("/auth/key", headers={"X-API-Key": key})
        self.assertEqual(signin.status_code, 200, signin.get_json())
        loans = self.client.get("/api/loans?lender=dash1").get_json()
        self.assertEqual([l["loan_id"] for l in loans], ["B-9"])
