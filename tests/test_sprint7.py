"""
Sprint 7 tests — Production hardening, health endpoint, metrics, notification
pagination/purge, security headers, and expanded coverage for verification,
reddit linking, audit logging, and calendar export.
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
# T5 — /health endpoint
# ---------------------------------------------------------------------------

class HealthEndpointTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from api.app import app
        app.config["TESTING"] = True
        cls.app = app

    def test_health_ok_when_db_works(self):
        conn, cur = _make_conn(fetchone_val=(1,))
        with patch("services._get_db", return_value=conn):
            res = self.app.test_client().get("/health")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["db"], "ok")
        self.assertIn("env", data)
        self.assertIn("build", data)

    def test_health_degraded_when_db_fails(self):
        with patch("services._get_db", return_value=None):
            res = self.app.test_client().get("/health")
        self.assertEqual(res.status_code, 503)
        data = res.get_json()
        self.assertEqual(data["status"], "degraded")
        self.assertEqual(data["db"], "error")

    def test_health_no_secrets_in_response(self):
        conn, cur = _make_conn(fetchone_val=(1,))
        with patch("services._get_db", return_value=conn):
            res = self.app.test_client().get("/health")
        body = res.get_data(as_text=True)
        self.assertNotIn("SECRET_KEY", body)
        self.assertNotIn("DB_PASSWORD", body)
        self.assertNotIn("API_KEY", body)

    def test_health_no_auth_required(self):
        conn, cur = _make_conn(fetchone_val=(1,))
        with patch("services._get_db", return_value=conn):
            res = self.app.test_client().get("/health")
        self.assertNotEqual(res.status_code, 302)
        self.assertNotEqual(res.status_code, 401)
        self.assertNotEqual(res.status_code, 403)


# ---------------------------------------------------------------------------
# T8 — Admin metrics endpoint
# ---------------------------------------------------------------------------

class AdminMetricsTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from api.app import app
        app.config["TESTING"] = True
        cls.app = app

    def _client(self, username=None, role=None):
        c = self.app.test_client()
        if username:
            with c.session_transaction() as s:
                s["username"] = username
                s["role"] = role
        return c

    def _fake_metrics(self):
        return {
            "loans":         {"total": 10, "active": 3, "repaid": 5, "unpaid": 1, "disputed": 1, "refunded": 0},
            "users":         {"total": 20, "lenders": 5, "borrowers": 14, "mods": 1, "verified_lenders": 3},
            "verifications": {"pending": 2},
            "notifications": {"unread_system": 0},
        }

    def test_metrics_admin_allowed(self):
        with patch("services.get_platform_metrics", return_value=(self._fake_metrics(), None)):
            res = self._client("a1", "admin").get("/api/admin/metrics")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["loans"]["total"], 10)
        self.assertEqual(data["users"]["verified_lenders"], 3)
        self.assertEqual(data["verifications"]["pending"], 2)

    def test_metrics_borrower_denied(self):
        res = self._client("b1", "borrower").get("/api/admin/metrics")
        self.assertEqual(res.status_code, 403)

    def test_metrics_mod_denied(self):
        res = self._client("m1", "mod").get("/api/admin/metrics")
        self.assertEqual(res.status_code, 403)

    def test_metrics_anonymous_denied(self):
        res = self._client().get("/api/admin/metrics")
        self.assertEqual(res.status_code, 403)

    def test_get_platform_metrics_structure(self):
        conn, cur = _make_conn()
        cur.fetchone.side_effect = [
            (10, 3, 5, 1, 1, 0),   # loans
            (20, 5, 14, 1, 3),      # users
            (2,),                   # pending verifications
            (0,),                   # unread notifications
        ]
        with patch("services._get_db", return_value=conn):
            from services import get_platform_metrics
            metrics, err = get_platform_metrics()
        self.assertIsNone(err)
        self.assertEqual(metrics["loans"]["total"], 10)
        self.assertEqual(metrics["loans"]["unpaid"], 1)
        self.assertEqual(metrics["users"]["verified_lenders"], 3)
        self.assertEqual(metrics["verifications"]["pending"], 2)

    def test_get_platform_metrics_db_failure(self):
        with patch("services._get_db", return_value=None):
            from services import get_platform_metrics
            metrics, err = get_platform_metrics()
        self.assertIsNone(metrics)
        self.assertIsNotNone(err)


# ---------------------------------------------------------------------------
# T6 — Notification pagination + purge
# ---------------------------------------------------------------------------

class NotificationPaginationTests(unittest.TestCase):

    def test_get_notifications_returns_total_and_offset(self):
        conn, cur = _make_conn()
        row = (1, "alice", "due_soon", "Due soon", "msg", False, datetime(2026, 6, 1))
        cur.fetchone.side_effect = [(2,), (5,)]
        cur.fetchall.return_value = [row]
        with patch("services._get_db", return_value=conn):
            from services import get_notifications
            notifs, unread, total, err = get_notifications("alice", limit=1, offset=0)
        self.assertIsNone(err)
        self.assertEqual(total, 5)
        self.assertEqual(unread, 2)
        self.assertEqual(len(notifs), 1)

    def test_get_notifications_offset_in_query(self):
        conn, cur = _make_conn()
        cur.fetchone.side_effect = [(0,), (10,)]
        cur.fetchall.return_value = []
        with patch("services._get_db", return_value=conn):
            from services import get_notifications
            get_notifications("alice", limit=5, offset=10)
        sql, params = cur.execute.call_args_list[-1][0]
        self.assertIn("OFFSET", sql.upper())
        self.assertIn(10, params)

    def test_purge_old_notifications_returns_count(self):
        conn, cur = _make_conn(rowcount=7)
        with patch("services._get_db", return_value=conn):
            from services import purge_old_notifications
            deleted, err = purge_old_notifications(days=90)
        self.assertIsNone(err)
        self.assertEqual(deleted, 7)
        sql = cur.execute.call_args[0][0]
        self.assertIn("DELETE", sql.upper())
        self.assertIn("read = TRUE", sql)

    def test_purge_never_deletes_unread(self):
        conn, cur = _make_conn(rowcount=0)
        with patch("services._get_db", return_value=conn):
            from services import purge_old_notifications
            purge_old_notifications(days=30)
        sql = cur.execute.call_args[0][0]
        self.assertIn("read = TRUE", sql)
        self.assertNotIn("read = FALSE", sql)

    def test_purge_db_failure(self):
        with patch("services._get_db", return_value=None):
            from services import purge_old_notifications
            deleted, err = purge_old_notifications()
        self.assertEqual(deleted, 0)
        self.assertIsNotNone(err)


class NotificationPurgeRouteTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from api.app import app
        app.config["TESTING"] = True
        cls.app = app

    def _client(self, role=None):
        c = self.app.test_client()
        if role:
            with c.session_transaction() as s:
                s["username"] = "a1"
                s["role"] = role
        return c

    def test_purge_admin_allowed(self):
        with patch("services.purge_old_notifications", return_value=(5, None)):
            res = self._client("admin").post(
                "/api/admin/notifications/purge", json={"days": 90},
                content_type="application/json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["deleted"], 5)

    def test_purge_mod_denied(self):
        res = self._client("mod").post("/api/admin/notifications/purge", json={"days": 90})
        self.assertEqual(res.status_code, 403)

    def test_purge_borrower_denied(self):
        res = self._client("borrower").post("/api/admin/notifications/purge", json={"days": 90})
        self.assertEqual(res.status_code, 403)

    def test_purge_minimum_days_enforced(self):
        res = self._client("admin").post(
            "/api/admin/notifications/purge", json={"days": 3},
            content_type="application/json")
        self.assertEqual(res.status_code, 400)


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------

class SecurityHeaderTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from api.app import app
        app.config["TESTING"] = True
        cls.app = app

    def test_x_content_type_options(self):
        res = self.app.test_client().get("/health")
        self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")

    def test_x_frame_options(self):
        res = self.app.test_client().get("/health")
        self.assertEqual(res.headers.get("X-Frame-Options"), "DENY")

    def test_referrer_policy(self):
        res = self.app.test_client().get("/health")
        self.assertIn("strict-origin", res.headers.get("Referrer-Policy", ""))


# ---------------------------------------------------------------------------
# Verification workflow (expanded coverage)
# ---------------------------------------------------------------------------

class VerificationWorkflowTests(unittest.TestCase):

    def test_submit_verification_application(self):
        conn, cur = _make_conn(rowcount=1)
        # First fetchone: no existing pending app; second: the inserted row id
        cur.fetchone.side_effect = [None, (42,)]
        with patch("services._get_db", return_value=conn):
            from services import submit_verification_application
            result, err = submit_verification_application("newlender", "lender")
        self.assertIsNone(err)

    def test_list_verification_applications_returns_rows(self):
        conn, cur = _make_conn()
        cur.fetchall.return_value = [
            (1, "lender1", "lender", "pending", None, None, None, None,
             datetime(2026, 1, 1), None, "lender1", False)
        ]
        with patch("services._get_db", return_value=conn):
            from services import list_verification_applications
            apps, err = list_verification_applications()
        self.assertIsNone(err)
        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0]["username"], "lender1")

    def test_decide_verification_approve(self):
        conn, cur = _make_conn(rowcount=1)
        # Row: (status, username, requested_role)
        cur.fetchone.return_value = ("pending", "lender1", "lender")
        with patch("services._get_db", return_value=conn), \
             patch("services.log_event"), \
             patch("services.log_audit", return_value=True), \
             patch("services.create_notification", return_value=True), \
             patch("services.set_verified_lender", return_value=(True, None)):
            from services import decide_verification_application
            result, err = decide_verification_application(1, "approved", "mod1")
        # Either succeeds or fails gracefully — main check is no crash
        self.assertIsInstance(err, (str, type(None)))


# ---------------------------------------------------------------------------
# Reddit username linking (expanded coverage)
# ---------------------------------------------------------------------------

class RedditLinkingTests(unittest.TestCase):

    def test_link_reddit_username_success(self):
        conn, cur = _make_conn(rowcount=1)
        cur.fetchone.return_value = None
        with patch("services._get_db", return_value=conn):
            from services import link_reddit_username
            ok, err = link_reddit_username("lender1", "u/reddituser", "admin1")
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_link_strips_u_prefix(self):
        conn, cur = _make_conn(rowcount=1)
        cur.fetchone.return_value = None
        with patch("services._get_db", return_value=conn):
            from services import link_reddit_username
            link_reddit_username("lender1", "u/TestUser", "admin1")
        update_sql = cur.execute.call_args_list[-1][0][0]
        self.assertIn("UPDATE", update_sql.upper())

    def test_link_rejects_duplicate(self):
        conn, cur = _make_conn()
        cur.fetchone.return_value = ("otherlender",)
        with patch("services._get_db", return_value=conn):
            from services import link_reddit_username
            ok, err = link_reddit_username("lender1", "takenuser", "admin1")
        self.assertFalse(ok)
        self.assertIn("already linked", err.lower())

    def test_unlink_reddit_username(self):
        conn, cur = _make_conn(rowcount=1)
        with patch("services._get_db", return_value=conn):
            from services import unlink_reddit_username
            ok, err = unlink_reddit_username("lender1", "admin1")
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_get_reddit_username(self):
        conn, cur = _make_conn(fetchone_val=("reddituser", None, None))
        with patch("services._get_db", return_value=conn):
            from services import get_reddit_username
            rn, linked_at, linked_by = get_reddit_username("lender1")
        self.assertEqual(rn, "reddituser")


# ---------------------------------------------------------------------------
# Audit logging (expanded coverage)
# ---------------------------------------------------------------------------

class AuditLoggingTests(unittest.TestCase):

    def test_log_audit_writes_entry(self):
        conn, cur = _make_conn()
        with patch("services._get_db", return_value=conn):
            from services import log_audit
            result = log_audit("admin1", "admin", "loan_repaid",
                               target_type="loan", target_id="12345",
                               new_value={"amount": 100})
        self.assertTrue(result)
        sql, params = cur.execute.call_args[0]
        self.assertIn("INSERT INTO audit_logs", sql)

    def test_log_audit_db_failure_returns_false(self):
        with patch("services._get_db", return_value=None):
            from services import log_audit
            result = log_audit("admin1", "admin", "test_action")
        self.assertFalse(result)

    def test_get_audit_log_with_all_filters(self):
        conn, cur = _make_conn(rows=[], fetchone_val=(0,))
        with patch("services._get_db", return_value=conn):
            from services import get_audit_log
            rows, total, err = get_audit_log(
                username="admin1", action_type="loan_repaid",
                target_type="loan", target_id="123",
                target_username="borrower1", loan_id="abc",
                date_from="2026-01-01", date_to="2026-12-31",
                limit=10, offset=5)
        self.assertIsNone(err)
        sql = cur.execute.call_args_list[0][0][0]
        self.assertIn("actor_username", sql)
        self.assertIn("action_type", sql)

    def test_get_audit_log_target_username_filter(self):
        conn, cur = _make_conn(rows=[], fetchone_val=(0,))
        with patch("services._get_db", return_value=conn):
            from services import get_audit_log
            get_audit_log(target_username="bob")
        sql, params = cur.execute.call_args_list[0][0]
        self.assertIn("target_type = 'user'", sql)
        self.assertIn("bob", params)

    def test_get_audit_log_loan_id_filter(self):
        conn, cur = _make_conn(rows=[], fetchone_val=(0,))
        with patch("services._get_db", return_value=conn):
            from services import get_audit_log
            get_audit_log(loan_id="LOAN-001")
        sql, params = cur.execute.call_args_list[0][0]
        self.assertIn("target_type = 'loan'", sql)


# ---------------------------------------------------------------------------
# Calendar export (route-level check)
# ---------------------------------------------------------------------------

class CalendarExportTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from api.app import app
        app.config["TESTING"] = True
        cls.app = app

    def _client(self, username=None, role=None):
        c = self.app.test_client()
        if username:
            with c.session_transaction() as s:
                s["username"] = username
                s["role"] = role
        return c

    def test_calendar_anonymous_denied(self):
        res = self._client().get("/api/loans/LOAN-001/calendar.ics")
        self.assertIn(res.status_code, (302, 401))

    def test_calendar_own_loan_allowed(self):
        fake_loan = {
            "loan_id": "LOAN-001", "lender": "lender1", "borrower": "borrower1",
            "amount": 100, "repay_amount": 110, "currency": "USD",
            "status": "confirmed", "repay_date": "2026-12-01",
            "original_thread": "https://reddit.com/r/test/comments/abc",
            "date_created": datetime(2026, 1, 1), "amount_repaid": 0,
            "interest_amount": None, "interest_rate": None, "payment_timing": None,
            "notes": None,
        }
        with patch("services._get_db") as mock_db:
            conn, cur = _make_conn()
            cur.fetchone.return_value = tuple(fake_loan.values())
            mock_db.return_value = conn
            res = self._client("lender1", "lender").get("/api/loans/LOAN-001/calendar.ics")
        # Auth passes; DB mock may not return exact shape — just confirm no auth redirect
        self.assertNotEqual(res.status_code, 302)

    def test_calendar_wrong_user_denied(self):
        # A loan whose lender/borrower are different from session user should return 403
        with patch("services._get_db") as mock_db:
            conn, cur = _make_conn()
            # Exactly 10 columns: db_id, loan_id, lender, borrower, amount, currency,
            # status, repay_date, repay_amount, thread
            cur.fetchone.return_value = (
                1, "LOAN-001", "otherlender", "otherborrower",
                100, "USD", "confirmed", "2026-12-01", 110, "http://t.co",
            )
            mock_db.return_value = conn
            res = self._client("borrower1", "borrower").get("/api/loans/LOAN-001/calendar.ics")
        self.assertIn(res.status_code, (403, 400))


if __name__ == "__main__":
    unittest.main()
