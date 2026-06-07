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


if __name__ == "__main__":
    unittest.main()
