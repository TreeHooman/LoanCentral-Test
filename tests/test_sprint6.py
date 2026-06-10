"""
Sprint 6 tests — Admin lender directory, lender profile, expanded admin
profile backend, global search upgrade, audit log filters, and route
permission hardening.

Service tests mock the DB (services._get_db). Route tests use the Flask
test client with session roles and patch service functions so no real
database is touched.
"""
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime


def _make_conn(rows=None, fetchone_val=None, rowcount=1):
    cur = MagicMock()
    cur.fetchone.return_value = fetchone_val
    cur.fetchall.return_value = rows or []
    cur.rowcount = rowcount
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn, cur


# ---------------------------------------------------------------------------
# T2 — list_lenders (lender directory backend)
# ---------------------------------------------------------------------------

class ListLendersTests(unittest.TestCase):

    def _row(self):
        return ("lender1", "lender", "redditname", True,
                datetime(2026, 1, 1), "admin1", datetime(2026, 6, 1),
                5, 2, 3, 0, 0, "500.00")

    def test_returns_lender_rows(self):
        conn, cur = _make_conn(rows=[self._row()], fetchone_val=(1,))
        with patch("services._get_db", return_value=conn):
            from services import list_lenders
            rows, total, err = list_lenders()
        self.assertIsNone(err)
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["username"], "lender1")
        self.assertTrue(rows[0]["verified_lender"])
        self.assertEqual(rows[0]["total_funded"], 500.0)
        self.assertEqual(rows[0]["total_loans"], 5)

    def test_verified_filter_in_sql(self):
        conn, cur = _make_conn(rows=[], fetchone_val=(0,))
        with patch("services._get_db", return_value=conn):
            from services import list_lenders
            list_lenders(verified_filter="verified")
        sql = cur.execute.call_args_list[0][0][0]
        self.assertIn("ur.verified_lender = TRUE", sql)

    def test_revoked_filter_in_sql(self):
        conn, cur = _make_conn(rows=[], fetchone_val=(0,))
        with patch("services._get_db", return_value=conn):
            from services import list_lenders
            list_lenders(verified_filter="revoked")
        sql = cur.execute.call_args_list[0][0][0]
        self.assertIn("verified_lender_at IS NOT NULL", sql)

    def test_search_param_passed(self):
        conn, cur = _make_conn(rows=[], fetchone_val=(0,))
        with patch("services._get_db", return_value=conn):
            from services import list_lenders
            list_lenders(q="bob")
        params = cur.execute.call_args_list[0][0][1]
        self.assertIn("%bob%", params)

    def test_no_private_notes_in_query(self):
        conn, cur = _make_conn(rows=[], fetchone_val=(0,))
        with patch("services._get_db", return_value=conn):
            from services import list_lenders
            list_lenders()
        for call in cur.execute.call_args_list:
            self.assertNotIn("private_note", call[0][0])


# ---------------------------------------------------------------------------
# T3/T4 — get_admin_user_profile
# ---------------------------------------------------------------------------

class AdminUserProfileTests(unittest.TestCase):

    def test_full_profile_fields(self):
        conn, cur = _make_conn()
        ident = ("lender1", "lender", "redditname", True,
                 datetime(2026, 1, 1), "admin1", 3,
                 datetime(2025, 12, 1), datetime(2026, 6, 1))
        cur.fetchone.side_effect = [ident, ("100.00", "0.00")]
        cur.fetchall.side_effect = [
            [("repaid", 3, "300.00"), ("confirmed", 2, "200.00")],  # as lender
            [("repaid", 1, "50.00")],                                # as borrower
            [],  # loan events
            [],  # audit logs
            [],  # verification applications
        ]
        with patch("services._get_db", return_value=conn):
            from services import get_admin_user_profile
            profile, err = get_admin_user_profile("lender1")
        self.assertIsNone(err)
        self.assertEqual(profile["role"], "lender")
        self.assertEqual(profile["perm_version"], 3)
        self.assertTrue(profile["verified_lender"])
        self.assertEqual(profile["loans_as_lender_total"], 5)
        self.assertEqual(profile["loans_as_lender_by_status"]["repaid"], 3)
        self.assertEqual(profile["total_amount_funded"], 500.0)
        self.assertEqual(profile["loans_as_borrower_total"], 1)
        self.assertEqual(profile["total_amount_borrowed"], 50.0)
        self.assertEqual(profile["outstanding_as_lender"], 100.0)
        self.assertIn("recent_loan_events", profile)
        self.assertIn("recent_audit_logs", profile)

    def test_unknown_user_returns_empty_profile(self):
        conn, cur = _make_conn()
        cur.fetchone.side_effect = [None, ("0", "0")]
        cur.fetchall.side_effect = [[], [], [], [], []]
        with patch("services._get_db", return_value=conn):
            from services import get_admin_user_profile
            profile, err = get_admin_user_profile("ghost")
        self.assertIsNone(err)
        self.assertIsNone(profile["role"])
        self.assertFalse(profile["verified_lender"])
        self.assertEqual(profile["perm_version"], 0)

    def test_verification_apps_exclude_private_note(self):
        conn, cur = _make_conn()
        cur.fetchone.side_effect = [None, ("0", "0")]
        cur.fetchall.side_effect = [[], [], [], [], []]
        with patch("services._get_db", return_value=conn):
            from services import get_admin_user_profile
            get_admin_user_profile("x")
        for call in cur.execute.call_args_list:
            self.assertNotIn("private_note", call[0][0])


# ---------------------------------------------------------------------------
# T5 — global_search upgrades
# ---------------------------------------------------------------------------

class GlobalSearchUpgradeTests(unittest.TestCase):

    def test_status_keyword_becomes_status_filter(self):
        conn, cur = _make_conn(rows=[])
        with patch("services._get_db", return_value=conn):
            from services import global_search
            results, total, err = global_search("unpaid", search_type="loans")
        self.assertIsNone(err)
        sql, params = cur.execute.call_args_list[0][0]
        self.assertIn("status = %s", sql)
        self.assertIn("unpaid", params)

    def test_verifications_group_returned(self):
        conn, cur = _make_conn(rows=[])
        verif_row = (7, "applicant1", "lender", "pending", None,
                     datetime(2026, 5, 1), "redditguy")
        cur.fetchall.side_effect = [[], [], [verif_row]]
        with patch("services._get_db", return_value=conn):
            from services import global_search
            results, total, err = global_search("applicant1", search_type="all")
        self.assertIsNone(err)
        self.assertEqual(len(results["verifications"]), 1)
        self.assertEqual(results["verifications"][0]["username"], "applicant1")
        self.assertEqual(results["verifications"][0]["status"], "pending")

    def test_verifications_never_include_private_note(self):
        conn, cur = _make_conn(rows=[])
        cur.fetchall.side_effect = [[], [], []]
        with patch("services._get_db", return_value=conn):
            from services import global_search
            global_search("x", search_type="verifications")
        for call in cur.execute.call_args_list:
            self.assertNotIn("private_note", call[0][0])

    def test_verification_status_keyword(self):
        conn, cur = _make_conn(rows=[])
        cur.fetchall.side_effect = [[]]
        with patch("services._get_db", return_value=conn):
            from services import global_search
            global_search("pending", search_type="verifications")
        sql, params = cur.execute.call_args_list[0][0]
        self.assertIn("va.status = %s", sql)
        self.assertIn("pending", params)


# ---------------------------------------------------------------------------
# T6 — audit log filters
# ---------------------------------------------------------------------------

class AuditLogFilterTests(unittest.TestCase):

    def test_target_username_filter(self):
        conn, cur = _make_conn(rows=[], fetchone_val=(0,))
        with patch("services._get_db", return_value=conn):
            from services import get_audit_log
            get_audit_log(target_username="bob")
        sql = cur.execute.call_args_list[0][0][0]
        self.assertIn("target_type = 'user'", sql)

    def test_loan_id_filter(self):
        conn, cur = _make_conn(rows=[], fetchone_val=(0,))
        with patch("services._get_db", return_value=conn):
            from services import get_audit_log
            get_audit_log(loan_id="12345")
        sql = cur.execute.call_args_list[0][0][0]
        self.assertIn("target_type = 'loan'", sql)

    def test_actor_filter_still_works(self):
        conn, cur = _make_conn(rows=[], fetchone_val=(0,))
        with patch("services._get_db", return_value=conn):
            from services import get_audit_log
            get_audit_log(username="alice", action_type="loan_repaid")
        sql, params = cur.execute.call_args_list[0][0]
        self.assertIn("actor_username", sql)
        self.assertIn("alice", params)
        self.assertIn("loan_repaid", params)


# ---------------------------------------------------------------------------
# T2/T3/T7 — Route permission tests (Flask test client)
# ---------------------------------------------------------------------------

class RoutePermissionTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from api.app import app
        app.config["TESTING"] = True
        cls.app = app

    def _client(self, username=None, role=None):
        client = self.app.test_client()
        if username:
            with client.session_transaction() as s:
                s["username"] = username
                s["role"] = role
        return client

    # --- lender directory API ---

    def test_lender_directory_anonymous_denied(self):
        res = self._client().get("/api/admin/lenders")
        self.assertEqual(res.status_code, 403)

    def test_lender_directory_borrower_denied(self):
        res = self._client("b1", "borrower").get("/api/admin/lenders")
        self.assertEqual(res.status_code, 403)

    def test_lender_directory_lender_denied(self):
        res = self._client("l1", "lender").get("/api/admin/lenders")
        self.assertEqual(res.status_code, 403)

    def test_lender_directory_mod_denied(self):
        # Intentional: lender directory is admin-only, mods use the mod dashboard
        res = self._client("m1", "mod").get("/api/admin/lenders")
        self.assertEqual(res.status_code, 403)

    def test_lender_directory_admin_allowed(self):
        with patch("services.list_lenders", return_value=([], 0, None)):
            res = self._client("a1", "admin").get("/api/admin/lenders")
        self.assertEqual(res.status_code, 200)
        self.assertIn("lenders", res.get_json())

    def test_lender_directory_invalid_filter_rejected(self):
        res = self._client("a1", "admin").get("/api/admin/lenders?verified=bogus")
        self.assertEqual(res.status_code, 400)

    def test_lender_directory_filters_passed_through(self):
        with patch("services.list_lenders", return_value=([], 0, None)) as m:
            self._client("a1", "admin").get(
                "/api/admin/lenders?verified=verified&has_reddit=1&q=bob")
        kwargs = m.call_args[1]
        self.assertEqual(kwargs["verified_filter"], "verified")
        self.assertTrue(kwargs["has_reddit"])
        self.assertEqual(kwargs["q"], "bob")

    # --- lender directory page ---

    def test_lender_directory_page_redirects_non_admin(self):
        res = self._client("m1", "mod").get("/dashboard/admin/lenders")
        self.assertEqual(res.status_code, 302)

    def test_lender_directory_page_anonymous_redirects(self):
        res = self._client().get("/dashboard/admin/lenders")
        self.assertEqual(res.status_code, 302)

    # --- lender profile API ---

    def test_lender_profile_borrower_denied(self):
        res = self._client("b1", "borrower").get("/api/admin/lenders/lender1")
        self.assertEqual(res.status_code, 403)

    def test_lender_profile_mod_denied(self):
        res = self._client("m1", "mod").get("/api/admin/lenders/lender1")
        self.assertEqual(res.status_code, 403)

    def test_lender_profile_admin_allowed(self):
        fake_profile = {"username": "lender1", "role": "lender",
                        "verified_lender": True, "perm_version": 1}
        with patch("services.get_admin_user_profile",
                   return_value=(fake_profile, None)), \
             patch("services.get_loan_history", return_value=([], None)):
            res = self._client("a1", "admin").get("/api/admin/lenders/lender1")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["username"], "lender1")
        self.assertEqual(data["loans"], [])

    def test_lender_profile_page_non_admin_redirects(self):
        res = self._client("l1", "lender").get("/dashboard/admin/lenders/lender1")
        self.assertEqual(res.status_code, 302)

    # --- existing sensitive routes: regression sweep ---

    def test_verified_lender_toggle_borrower_denied(self):
        res = self._client("b1", "borrower").post(
            "/api/admin/verified-lender/x", json={"verified": True})
        self.assertEqual(res.status_code, 403)

    def test_reddit_link_anonymous_denied(self):
        res = self._client().post(
            "/api/admin/users/x/reddit-link", json={"reddit_username": "y"})
        self.assertEqual(res.status_code, 403)

    def test_reddit_link_lender_denied(self):
        res = self._client("l1", "lender").post(
            "/api/admin/users/x/reddit-link", json={"reddit_username": "y"})
        self.assertEqual(res.status_code, 403)

    def test_audit_log_borrower_denied(self):
        res = self._client("b1", "borrower").get("/api/admin/audit-log")
        self.assertEqual(res.status_code, 403)

    def test_global_search_borrower_denied(self):
        res = self._client("b1", "borrower").get("/api/admin/search?q=x")
        self.assertEqual(res.status_code, 403)

    def test_global_search_anonymous_denied(self):
        res = self._client().get("/api/admin/search?q=x")
        self.assertEqual(res.status_code, 403)

    def test_verification_queue_borrower_denied(self):
        res = self._client("b1", "borrower").get("/api/verification")
        self.assertIn(res.status_code, (403, 404))

    def test_roles_api_borrower_denied(self):
        res = self._client("b1", "borrower").get("/api/admin/roles")
        self.assertEqual(res.status_code, 403)

    def test_integrity_borrower_denied(self):
        res = self._client("b1", "borrower").get("/api/admin/integrity")
        self.assertEqual(res.status_code, 403)

    def test_admin_keys_borrower_denied(self):
        res = self._client("b1", "borrower").get("/api/admin/keys")
        self.assertEqual(res.status_code, 403)

    def test_integrity_admin_allowed(self):
        # Regression: was role_required("mod") which locked out admins
        with patch("services.run_integrity_checks", return_value=([], None)):
            res = self._client("a1", "admin").get("/api/admin/integrity")
        self.assertEqual(res.status_code, 200)

    def test_create_key_borrower_denied(self):
        res = self._client("b1", "borrower").post(
            "/api/admin/keys", json={"username": "x"})
        self.assertIn(res.status_code, (302, 403))

    def test_revoke_key_mod_denied(self):
        res = self._client("m1", "mod").post("/api/admin/keys/1/revoke")
        self.assertIn(res.status_code, (302, 403))

    def test_notifications_anonymous_redirects(self):
        res = self._client().get("/api/notifications")
        self.assertIn(res.status_code, (302, 401))


if __name__ == "__main__":
    unittest.main()
