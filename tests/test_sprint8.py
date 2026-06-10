"""
Sprint 8 tests — Feedback system, notification preferences, expanded metrics,
user activity timeline, beta analytics, and new API routes.
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


# =============================================================================
# Feedback service tests
# =============================================================================

class FeedbackServiceTests(unittest.TestCase):

    def test_create_feedback_valid(self):
        from services import create_feedback
        conn, cur = _make_conn(fetchone_val=(42,))
        with patch("services._get_db", return_value=conn):
            fid, err = create_feedback("alice", "bug", "Login broken", "Steps to reproduce...")
        self.assertIsNone(err)
        self.assertEqual(fid, 42)
        conn.commit.assert_called_once()

    def test_create_feedback_invalid_category(self):
        from services import create_feedback
        fid, err = create_feedback("alice", "spam", "title", "desc")
        self.assertIsNone(fid)
        self.assertIn("Invalid category", err)

    def test_create_feedback_empty_title(self):
        from services import create_feedback
        fid, err = create_feedback("alice", "bug", "   ", "some description")
        self.assertIsNone(fid)
        self.assertIn("Title", err)

    def test_create_feedback_empty_description(self):
        from services import create_feedback
        fid, err = create_feedback("alice", "suggestion", "Good idea", "  ")
        self.assertIsNone(fid)
        self.assertIn("Description", err)

    def test_create_feedback_db_failure(self):
        from services import create_feedback
        with patch("services._get_db", return_value=None):
            fid, err = create_feedback("alice", "bug", "title", "desc")
        self.assertIsNone(fid)
        self.assertIn("Database", err)

    def test_create_feedback_truncates_title(self):
        from services import create_feedback
        conn, cur = _make_conn(fetchone_val=(1,))
        long_title = "x" * 300
        with patch("services._get_db", return_value=conn):
            fid, err = create_feedback("alice", "bug", long_title, "desc")
        self.assertIsNone(err)
        args = cur.execute.call_args[0][1]
        self.assertEqual(len(args[2]), 200)

    def test_get_feedback_list_no_filter(self):
        from services import get_feedback_list
        now = datetime(2026, 6, 9, 12, 0)
        conn, cur = _make_conn(rows=[
            (1, "alice", "bug", "Title", "Desc", "open", None, None, now, None)
        ], fetchone_val=(1,))
        with patch("services._get_db", return_value=conn):
            items, total, err = get_feedback_list()
        self.assertIsNone(err)
        self.assertEqual(total, 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["username"], "alice")

    def test_get_feedback_list_with_filters(self):
        from services import get_feedback_list
        conn, cur = _make_conn(rows=[], fetchone_val=(0,))
        with patch("services._get_db", return_value=conn):
            items, total, err = get_feedback_list(status="open", category="bug", username="alice")
        self.assertIsNone(err)
        self.assertEqual(items, [])

    def test_get_feedback_list_db_failure(self):
        from services import get_feedback_list
        with patch("services._get_db", return_value=None):
            items, total, err = get_feedback_list()
        self.assertEqual(items, [])
        self.assertEqual(total, 0)
        self.assertIsNotNone(err)

    def test_update_feedback_status_valid(self):
        from services import update_feedback_status
        conn, cur = _make_conn(rowcount=1)
        with patch("services._get_db", return_value=conn):
            ok, err = update_feedback_status(1, "reviewed", "mod1", "Looks good")
        self.assertTrue(ok)
        self.assertIsNone(err)
        conn.commit.assert_called_once()

    def test_update_feedback_status_invalid_status(self):
        from services import update_feedback_status
        ok, err = update_feedback_status(1, "nonsense", "mod1")
        self.assertFalse(ok)
        self.assertIn("Invalid status", err)

    def test_update_feedback_status_not_found(self):
        from services import update_feedback_status
        conn, cur = _make_conn(rowcount=0)
        with patch("services._get_db", return_value=conn):
            ok, err = update_feedback_status(999, "completed", "mod1")
        self.assertFalse(ok)
        self.assertIn("not found", err)

    def test_update_feedback_all_statuses(self):
        from services import update_feedback_status
        for status in ("open", "reviewed", "completed", "duplicate"):
            conn, cur = _make_conn(rowcount=1)
            with patch("services._get_db", return_value=conn):
                ok, err = update_feedback_status(1, status, "mod1")
            self.assertTrue(ok, f"status={status} should be valid")


# =============================================================================
# Notification preferences service tests
# =============================================================================

class NotifPrefsServiceTests(unittest.TestCase):

    def test_get_prefs_existing_user(self):
        from services import get_notification_preferences
        conn, cur = _make_conn(fetchone_val=(True, False, True, True))
        with patch("services._get_db", return_value=conn):
            prefs, err = get_notification_preferences("alice")
        self.assertIsNone(err)
        self.assertTrue(prefs["due_date_reminders"])
        self.assertFalse(prefs["status_updates"])
        self.assertTrue(prefs["verification_updates"])

    def test_get_prefs_new_user_returns_defaults(self):
        from services import get_notification_preferences
        conn, cur = _make_conn(fetchone_val=None)
        with patch("services._get_db", return_value=conn):
            prefs, err = get_notification_preferences("newuser")
        self.assertIsNone(err)
        self.assertTrue(prefs["due_date_reminders"])
        self.assertTrue(prefs["status_updates"])
        self.assertTrue(prefs["verification_updates"])
        self.assertTrue(prefs["dispute_updates"])

    def test_get_prefs_db_failure_returns_defaults(self):
        from services import get_notification_preferences
        with patch("services._get_db", return_value=None):
            prefs, err = get_notification_preferences("alice")
        self.assertIsNotNone(err)
        # Still returns defaults even on failure
        self.assertIn("due_date_reminders", prefs)

    def test_update_prefs_success(self):
        from services import update_notification_preferences
        conn, cur = _make_conn()
        with patch("services._get_db", return_value=conn):
            ok, err = update_notification_preferences(
                "alice", True, False, True, False)
        self.assertTrue(ok)
        self.assertIsNone(err)
        conn.commit.assert_called_once()

    def test_update_prefs_db_failure(self):
        from services import update_notification_preferences
        with patch("services._get_db", return_value=None):
            ok, err = update_notification_preferences(
                "alice", True, True, True, True)
        self.assertFalse(ok)
        self.assertIsNotNone(err)

    def test_update_prefs_upsert_called(self):
        from services import update_notification_preferences
        conn, cur = _make_conn()
        with patch("services._get_db", return_value=conn):
            update_notification_preferences("alice", True, False, True, False)
        sql = cur.execute.call_args[0][0].upper()
        self.assertIn("INSERT", sql)
        self.assertIn("ON CONFLICT", sql)


# =============================================================================
# Expanded metrics service tests
# =============================================================================

class ExpandedMetricsTests(unittest.TestCase):

    def _mock_cursor_sequence(self, conn, cur, sequence):
        """Set up fetchone to return values from sequence in order."""
        cur.fetchone.side_effect = sequence

    def test_get_expanded_metrics_structure(self):
        from services import get_expanded_metrics
        conn, cur = _make_conn()
        cur.fetchone.side_effect = [
            (100, 40, 50, 5, 2, 3, 10, 8),  # loans
            (30, 15, 10, 2, 8, 6, 4),         # users
            (3, 5, 1),                          # verifications
            (7,),                               # unread notifs
            (2, 1, 3, 1, 7),                   # feedback
        ]
        with patch("services._get_db", return_value=conn):
            metrics, err = get_expanded_metrics()
        self.assertIsNone(err)
        self.assertIn("loans", metrics)
        self.assertIn("users", metrics)
        self.assertIn("verifications", metrics)
        self.assertIn("feedback", metrics)
        self.assertIn("disputes", metrics)
        self.assertEqual(metrics["loans"]["total"], 100)
        self.assertEqual(metrics["loans"]["created_this_month"], 10)
        self.assertEqual(metrics["loans"]["repayments_this_month"], 8)
        self.assertEqual(metrics["users"]["active_lenders"], 6)
        self.assertEqual(metrics["users"]["active_borrowers"], 4)
        self.assertEqual(metrics["verifications"]["approvals_this_month"], 5)
        self.assertEqual(metrics["feedback"]["open"], 2)
        self.assertEqual(metrics["feedback"]["total"], 7)

    def test_get_expanded_metrics_db_failure(self):
        from services import get_expanded_metrics
        with patch("services._get_db", return_value=None):
            metrics, err = get_expanded_metrics()
        self.assertIsNone(metrics)
        self.assertIsNotNone(err)


# =============================================================================
# User activity timeline service tests
# =============================================================================

class UserTimelineTests(unittest.TestCase):

    def test_get_user_activity_timeline_returns_list(self):
        from services import get_user_activity_timeline
        now = datetime(2026, 6, 9, 12, 0)
        conn, cur = _make_conn(rows=[
            ("audit", "role_granted", "mod1", now, "alice", "{}"),
            ("loan_event", "loan_created", "alice", now, "LC-001", ""),
        ])
        with patch("services._get_db", return_value=conn):
            events, err = get_user_activity_timeline("alice")
        self.assertIsNone(err)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["source"], "audit")
        self.assertIsInstance(events[0]["created_at"], str)

    def test_get_user_activity_timeline_empty(self):
        from services import get_user_activity_timeline
        conn, cur = _make_conn(rows=[])
        with patch("services._get_db", return_value=conn):
            events, err = get_user_activity_timeline("nobody")
        self.assertIsNone(err)
        self.assertEqual(events, [])

    def test_get_user_activity_timeline_db_failure(self):
        from services import get_user_activity_timeline
        with patch("services._get_db", return_value=None):
            events, err = get_user_activity_timeline("alice")
        self.assertEqual(events, [])
        self.assertIsNotNone(err)


# =============================================================================
# Analytics service tests
# =============================================================================

class AnalyticsServiceTests(unittest.TestCase):

    def test_log_analytics_event_no_crash_on_db_failure(self):
        from services import log_analytics_event
        with patch("services._get_db", return_value=None):
            # Should not raise
            log_analytics_event("alice", "page_view", page="/feedback")

    def test_log_analytics_event_inserts(self):
        from services import log_analytics_event
        conn, cur = _make_conn()
        with patch("services._get_db", return_value=conn):
            log_analytics_event("alice", "search", page="/search", metadata={"q": "test"})
        cur.execute.assert_called_once()
        conn.commit.assert_called_once()

    def test_get_analytics_summary_structure(self):
        from services import get_analytics_summary
        conn, cur = _make_conn()
        cur.fetchall.side_effect = [
            [("page_view", 50), ("search", 12)],
            [("/feedback", 15), ("/dashboard", 35)],
        ]
        cur.fetchone.return_value = (8,)
        with patch("services._get_db", return_value=conn):
            summary, err = get_analytics_summary(30)
        self.assertIsNone(err)
        self.assertEqual(summary["period_days"], 30)
        self.assertIn("by_event_type", summary)
        self.assertIn("top_pages", summary)
        self.assertIn("unique_active_users", summary)
        self.assertEqual(summary["by_event_type"]["page_view"], 50)
        self.assertEqual(summary["unique_active_users"], 8)

    def test_get_analytics_summary_db_failure(self):
        from services import get_analytics_summary
        with patch("services._get_db", return_value=None):
            summary, err = get_analytics_summary()
        self.assertIsNone(summary)
        self.assertIsNotNone(err)


# =============================================================================
# API route tests
# =============================================================================

class FeedbackAPITests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from api.app import app
        app.config["TESTING"] = True
        cls.app = app

    def _auth_client(self, role="lender"):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["username"] = "testlender"
            sess["role"]     = role
        return client

    def test_submit_feedback_success(self):
        conn, cur = _make_conn(fetchone_val=(7,))
        with patch("services._get_db", return_value=conn):
            res = self._auth_client().post("/api/feedback",
                json={"category": "bug", "title": "Test bug", "description": "Steps here"})
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertIn("id", data)

    def test_submit_feedback_missing_title(self):
        conn, cur = _make_conn(fetchone_val=(1,))
        with patch("services._get_db", return_value=conn):
            res = self._auth_client().post("/api/feedback",
                json={"category": "bug", "title": "", "description": "desc"})
        self.assertEqual(res.status_code, 400)

    def test_submit_feedback_unauthenticated(self):
        res = self.app.test_client().post("/api/feedback",
            json={"category": "bug", "title": "t", "description": "d"})
        self.assertIn(res.status_code, (302, 401))

    def test_get_my_feedback(self):
        conn, cur = _make_conn(rows=[], fetchone_val=(0,))
        with patch("services._get_db", return_value=conn):
            res = self._auth_client().get("/api/feedback")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("feedback", data)
        self.assertIn("total", data)

    def test_admin_feedback_list_requires_auth(self):
        res = self.app.test_client().get("/api/admin/feedback")
        self.assertIn(res.status_code, (302, 401, 403))

    def test_admin_feedback_list_mod_access(self):
        conn, cur = _make_conn(rows=[], fetchone_val=(0,))
        with patch("services._get_db", return_value=conn):
            res = self._auth_client(role="mod").get("/api/admin/feedback")
        self.assertEqual(res.status_code, 200)

    def test_admin_feedback_update(self):
        conn, cur = _make_conn(rowcount=1)
        with patch("services._get_db", return_value=conn):
            res = self._auth_client(role="mod").patch("/api/admin/feedback/1",
                json={"status": "reviewed", "reviewer_note": "Noted"})
        self.assertEqual(res.status_code, 200)

    def test_admin_feedback_update_invalid_status(self):
        conn, cur = _make_conn(rowcount=1)
        with patch("services._get_db", return_value=conn):
            res = self._auth_client(role="mod").patch("/api/admin/feedback/1",
                json={"status": "garbage"})
        self.assertEqual(res.status_code, 400)


class NotifPrefsAPITests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from api.app import app
        app.config["TESTING"] = True
        cls.app = app

    def _auth_client(self):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["username"] = "alice"
            sess["role"]     = "borrower"
        return client

    def test_get_prefs(self):
        conn, cur = _make_conn(fetchone_val=(True, True, True, True))
        with patch("services._get_db", return_value=conn):
            res = self._auth_client().get("/api/notifications/preferences")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("due_date_reminders", data)
        self.assertIn("status_updates", data)

    def test_update_prefs(self):
        conn, cur = _make_conn()
        with patch("services._get_db", return_value=conn):
            res = self._auth_client().put("/api/notifications/preferences",
                json={"due_date_reminders": True, "status_updates": False,
                      "verification_updates": True, "dispute_updates": True})
        self.assertEqual(res.status_code, 200)

    def test_prefs_unauthenticated(self):
        res = self.app.test_client().get("/api/notifications/preferences")
        self.assertIn(res.status_code, (302, 401))


class ExpandedMetricsAPITests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from api.app import app
        app.config["TESTING"] = True
        cls.app = app

    def _admin_client(self):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["username"] = "admin1"
            sess["role"]     = "admin"
        return client

    def test_expanded_metrics_endpoint(self):
        conn, cur = _make_conn()
        cur.fetchone.side_effect = [
            (100, 40, 50, 5, 2, 3, 10, 8),
            (30, 15, 10, 2, 8, 6, 4),
            (3, 5, 1),
            (7,),
            (2, 1, 3, 1, 7),
        ]
        with patch("services._get_db", return_value=conn):
            res = self._admin_client().get("/api/admin/metrics/expanded")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("loans", data)
        self.assertIn("feedback", data)

    def test_expanded_metrics_requires_admin(self):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["username"] = "regularuser"
            sess["role"]     = "lender"
        conn, cur = _make_conn()
        with patch("services._get_db", return_value=conn):
            res = client.get("/api/admin/metrics/expanded")
        self.assertIn(res.status_code, (302, 403))


class AnalyticsAPITests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from api.app import app
        app.config["TESTING"] = True
        cls.app = app

    def _admin_client(self):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["username"] = "admin1"
            sess["role"]     = "admin"
        return client

    def test_analytics_summary(self):
        conn, cur = _make_conn()
        cur.fetchall.side_effect = [
            [("page_view", 50)],
            [("/feedback", 10)],
        ]
        cur.fetchone.return_value = (5,)
        with patch("services._get_db", return_value=conn):
            res = self._admin_client().get("/api/admin/analytics?days=7")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["period_days"], 7)

    def test_analytics_days_capped_at_365(self):
        conn, cur = _make_conn()
        cur.fetchall.side_effect = [[], []]
        cur.fetchone.return_value = (0,)
        with patch("services._get_db", return_value=conn):
            res = self._admin_client().get("/api/admin/analytics?days=9999")
        self.assertEqual(res.status_code, 200)


class UserTimelineAPITests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from api.app import app
        app.config["TESTING"] = True
        cls.app = app

    def _mod_client(self):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["username"] = "mod1"
            sess["role"]     = "mod"
        return client

    def test_timeline_api(self):
        now = datetime(2026, 6, 9, 12, 0)
        conn, cur = _make_conn(rows=[
            ("audit", "role_granted", "mod1", now, "alice", "{}"),
        ])
        with patch("services._get_db", return_value=conn):
            res = self._mod_client().get("/api/audit/user/alice/timeline")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("events", data)
        self.assertEqual(data["username"], "alice")

    def test_timeline_api_requires_mod(self):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["username"] = "borrower1"
            sess["role"]     = "borrower"
        conn, cur = _make_conn(rows=[])
        with patch("services._get_db", return_value=conn):
            res = client.get("/api/audit/user/alice/timeline")
        self.assertIn(res.status_code, (302, 403))


# =============================================================================
# Page render smoke tests
# =============================================================================

class PageRenderTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from api.app import app
        app.config["TESTING"] = True
        cls.app = app

    def _lender_client(self):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["username"] = "testlender"
            sess["role"]     = "lender"
            sess["verified_lender"] = False
        return client

    def _mod_client(self):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["username"] = "mod1"
            sess["role"]     = "mod"
        return client

    def test_feedback_page_loads(self):
        conn, cur = _make_conn(rows=[], fetchone_val=(0,))
        with patch("services._get_db", return_value=conn):
            res = self._lender_client().get("/feedback")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Feedback", res.data)

    def test_admin_feedback_page_loads_for_mod(self):
        conn, cur = _make_conn()
        with patch("services._get_db", return_value=conn):
            res = self._mod_client().get("/admin/feedback")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Feedback Dashboard", res.data)

    def test_admin_feedback_page_redirects_for_lender(self):
        conn, cur = _make_conn()
        with patch("services._get_db", return_value=conn):
            res = self._lender_client().get("/admin/feedback")
        self.assertEqual(res.status_code, 302)

    def test_audit_user_page_loads_for_mod(self):
        conn, cur = _make_conn(rows=[])
        with patch("services._get_db", return_value=conn):
            res = self._mod_client().get("/audit/user/someuser")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"someuser", res.data)

    def test_audit_user_page_redirects_for_lender(self):
        conn, cur = _make_conn(rows=[])
        with patch("services._get_db", return_value=conn):
            res = self._lender_client().get("/audit/user/someuser")
        self.assertEqual(res.status_code, 302)

    def test_feedback_page_unauthenticated(self):
        res = self.app.test_client().get("/feedback")
        self.assertIn(res.status_code, (302, 401))


if __name__ == "__main__":
    unittest.main()
