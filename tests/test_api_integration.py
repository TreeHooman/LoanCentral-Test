"""
Integration tests for Flask API endpoints using the test client.
These test the HTTP layer — status codes, response structure, and error handling.
No Reddit/DB credentials needed; graceful fallbacks are tested.
"""
import json
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.app import app


class HealthEndpointTests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test-secret"
        self.client = app.test_client()

    def test_health_returns_json(self):
        r = self.client.get("/api/health")
        self.assertIn(r.status_code, (200, 503))
        data = json.loads(r.data)
        self.assertIn("status", data)
        self.assertIn("db", data)
        self.assertIn("time", data)
        self.assertIn("version", data)

    def test_health_includes_bot_field(self):
        r = self.client.get("/api/health")
        data = json.loads(r.data)
        self.assertIn("bot", data)

    def test_health_status_reflects_db_state(self):
        r = self.client.get("/api/health")
        data = json.loads(r.data)
        if data["db"]:
            self.assertEqual(data["status"], "ok")
            self.assertEqual(r.status_code, 200)
        else:
            self.assertEqual(data["status"], "degraded")
            self.assertEqual(r.status_code, 503)

    def test_health_version_is_semver(self):
        r = self.client.get("/api/health")
        data = json.loads(r.data)
        parts = data["version"].split(".")
        self.assertEqual(len(parts), 3)


class AuthRequiredEndpointsTests(unittest.TestCase):
    """Endpoints that need auth should redirect or return 401/403 without a session."""

    def setUp(self):
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test-secret"
        self.client = app.test_client()

    def _assert_auth_required(self, path, method="GET", json_body=None):
        if method == "GET":
            r = self.client.get(path)
        else:
            r = self.client.post(path, json=json_body or {})
        # Must redirect to login OR return 401/403 — NOT 200
        self.assertNotEqual(r.status_code, 200,
                            f"{method} {path} returned 200 without auth")

    def test_mod_dashboard_requires_auth(self):
        self._assert_auth_required("/dashboard/mod")

    def test_lender_dashboard_requires_auth(self):
        self._assert_auth_required("/dashboard/lender")

    def test_borrower_dashboard_requires_auth(self):
        self._assert_auth_required("/dashboard/borrower")

    def test_leaderboard_page_requires_auth(self):
        self._assert_auth_required("/leaderboard")

    def test_stats_api_requires_auth(self):
        self._assert_auth_required("/api/stats")

    def test_loans_api_requires_auth(self):
        self._assert_auth_required("/api/loans")

    def test_audit_log_requires_auth(self):
        self._assert_auth_required("/api/audit-log")

    def test_bulk_action_requires_auth(self):
        self._assert_auth_required("/api/loans/bulk", method="POST",
                                   json_body={"ids": [1], "action": "unpaid"})


class LoginFlowTests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test-secret"
        self.client = app.test_client()

    def test_login_page_accessible(self):
        r = self.client.get("/login")
        self.assertEqual(r.status_code, 200)

    def test_login_post_bad_credentials(self):
        r = self.client.post("/auth/login", json={
            "username": "nonexistent_user_xyz",
            "password": "wrongpassword",
        })
        # Either 401 or redirect with flash
        self.assertNotEqual(r.status_code, 200, "Bad login should not return 200 with session")

    def test_privacy_page_accessible(self):
        r = self.client.get("/privacy")
        self.assertEqual(r.status_code, 200)


class PublicProfileTests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test-secret"
        self.client = app.test_client()

    def test_public_profile_404_for_unknown_user(self):
        # Profile page redirects to login without session, or shows profile if accessible
        r = self.client.get("/u/definitely_nonexistent_user_12345")
        # Acceptable: 200 (shows page), 302 (redirect to login), 404 (not found)
        self.assertIn(r.status_code, (200, 302, 404))


class CSVExportTests(unittest.TestCase):
    """CSV export endpoints — verify auth gates and content-type."""

    def setUp(self):
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test-secret"
        app.config["PROPAGATE_EXCEPTIONS"] = False
        self.client = app.test_client()

    def test_mod_export_requires_auth(self):
        r = self.client.get("/api/loans/export.csv")
        self.assertNotEqual(r.status_code, 200, "Mod CSV export should require auth")

    def test_my_export_requires_login(self):
        r = self.client.get("/api/loans/my-export.csv")
        # Without session must redirect or 401/403
        self.assertNotEqual(r.status_code, 200, "My-export CSV should require login")

    def test_my_export_with_session_returns_csv_or_error(self):
        with self.client.session_transaction() as sess:
            sess["username"] = "testlender"
            sess["role"] = "lender"
        r = self.client.get("/api/loans/my-export.csv")
        # With session: either CSV (200) or DB error (500) — never a redirect/auth error
        self.assertIn(r.status_code, (200, 500))
        if r.status_code == 200:
            self.assertIn("text/csv", r.content_type)
            # First line of CSV must be the header
            first_line = r.data.decode().splitlines()[0]
            self.assertIn("loan_id", first_line)
            self.assertIn("borrower", first_line)

    def test_my_export_csv_header_columns(self):
        with self.client.session_transaction() as sess:
            sess["username"] = "testlender"
            sess["role"] = "lender"
        r = self.client.get("/api/loans/my-export.csv")
        if r.status_code == 200:
            cols = r.data.decode().splitlines()[0].split(",")
            expected = {"loan_id", "borrower", "amount", "currency", "status"}
            self.assertTrue(expected.issubset(set(cols)))


class BorrowerStatsTests(unittest.TestCase):
    """Borrower stats endpoint."""

    def setUp(self):
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test-secret"
        app.config["PROPAGATE_EXCEPTIONS"] = False
        self.client = app.test_client()

    def test_borrower_stats_requires_auth(self):
        r = self.client.get("/api/stats/borrower/someuser")
        self.assertNotEqual(r.status_code, 200)

    def test_borrower_stats_own_data_allowed(self):
        with self.client.session_transaction() as sess:
            sess["username"] = "testborrower"
            sess["role"] = "borrower"
        r = self.client.get("/api/stats/borrower/testborrower")
        self.assertIn(r.status_code, (200, 500))
        if r.status_code == 200:
            data = json.loads(r.data)
            self.assertIn("total_loans", data)
            self.assertIn("outstanding", data)

    def test_borrower_stats_other_user_forbidden(self):
        with self.client.session_transaction() as sess:
            sess["username"] = "testborrower"
            sess["role"] = "borrower"
        r = self.client.get("/api/stats/borrower/differentuser")
        self.assertEqual(r.status_code, 403)


class OverdueLoansTests(unittest.TestCase):
    """Overdue loans endpoint — mod only."""

    def setUp(self):
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test-secret"
        self.client = app.test_client()

    def test_overdue_requires_mod(self):
        r = self.client.get("/api/loans/overdue")
        self.assertNotEqual(r.status_code, 200)

    def test_overdue_with_non_mod_session_forbidden(self):
        with self.client.session_transaction() as sess:
            sess["username"] = "somelender"
            sess["role"] = "lender"
        r = self.client.get("/api/loans/overdue")
        self.assertEqual(r.status_code, 403)

    def test_overdue_with_mod_session_returns_json(self):
        with self.client.session_transaction() as sess:
            sess["username"] = "moduser"
            sess["role"] = "mod"
        r = self.client.get("/api/loans/overdue")
        self.assertIn(r.status_code, (200, 500))
        if r.status_code == 200:
            data = json.loads(r.data)
            self.assertIsInstance(data, list)


class BanAPITests(unittest.TestCase):
    """Ban management endpoints — mod only."""

    def setUp(self):
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test-secret"
        app.config["PROPAGATE_EXCEPTIONS"] = False
        self.client = app.test_client()

    def _mod_session(self):
        with self.client.session_transaction() as sess:
            sess["username"] = "moduser"
            sess["role"] = "mod"

    def test_list_bans_requires_mod(self):
        r = self.client.get("/api/admin/bans")
        self.assertNotEqual(r.status_code, 200)

    def test_list_bans_non_mod_forbidden(self):
        with self.client.session_transaction() as sess:
            sess["username"] = "somelender"
            sess["role"] = "lender"
        r = self.client.get("/api/admin/bans")
        self.assertEqual(r.status_code, 403)

    def test_list_bans_mod_gets_json(self):
        self._mod_session()
        r = self.client.get("/api/admin/bans")
        self.assertIn(r.status_code, (200, 500))
        if r.status_code == 200:
            data = json.loads(r.data)
            self.assertIn("banned", data)
            self.assertIsInstance(data["banned"], list)

    def test_ban_user_requires_mod(self):
        r = self.client.post("/api/admin/bans/someuser",
                             json={"reason": "test"},
                             content_type="application/json")
        self.assertNotEqual(r.status_code, 200)

    def test_unban_user_requires_mod(self):
        r = self.client.delete("/api/admin/bans/someuser")
        self.assertNotEqual(r.status_code, 200)

    def test_ban_user_mod_returns_ok_or_db_error(self):
        self._mod_session()
        r = self.client.post("/api/admin/bans/testbaduser",
                             json={"reason": "integration test ban"},
                             content_type="application/json")
        self.assertIn(r.status_code, (200, 400, 500))

    def test_notes_requires_mod(self):
        r = self.client.get("/api/admin/notes/someuser")
        self.assertNotEqual(r.status_code, 200)

    def test_notes_mod_gets_json(self):
        self._mod_session()
        r = self.client.get("/api/admin/notes/someuser")
        self.assertIn(r.status_code, (200, 500))
        if r.status_code == 200:
            data = json.loads(r.data)
            self.assertIn("notes", data)


class AccountInfoTests(unittest.TestCase):
    """Account info endpoint."""

    def setUp(self):
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test-secret"
        app.config["PROPAGATE_EXCEPTIONS"] = False
        self.client = app.test_client()

    def test_account_info_requires_auth(self):
        r = self.client.get("/api/users/me/account")
        self.assertNotEqual(r.status_code, 200)

    def test_account_info_with_session(self):
        with self.client.session_transaction() as sess:
            sess["username"] = "testuser"
            sess["role"] = "borrower"
        r = self.client.get("/api/users/me/account")
        self.assertIn(r.status_code, (200, 500))
        if r.status_code == 200:
            data = json.loads(r.data)
            self.assertEqual(data["username"], "testuser")
            self.assertEqual(data["role"], "borrower")
            self.assertIn("last_login", data)
            self.assertIn("member_since", data)
            self.assertIn("is_banned", data)


if __name__ == "__main__":
    unittest.main()
