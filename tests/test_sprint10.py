"""
Sprint 10 tests — Mod queue, community health, lender management,
borrower activity, announcements, audit investigation summary, and API routes.
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


def _make_multi_conn(*fetchone_sequence):
    """Conn whose fetchone returns each value in sequence on successive calls."""
    cur = MagicMock()
    cur.fetchone.side_effect = list(fetchone_sequence)
    cur.fetchall.return_value = []
    cur.rowcount = 1
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn, cur


# =============================================================================
# Announcement service tests
# =============================================================================

class AnnouncementServiceTests(unittest.TestCase):

    def test_create_announcement_valid(self):
        from services import create_announcement
        conn, cur = _make_conn(fetchone_val=(7,))
        with patch("services._get_db", return_value=conn):
            aid, err = create_announcement("Hello", "Body text", "admin_user")
        self.assertIsNone(err)
        self.assertEqual(aid, 7)
        conn.commit.assert_called_once()

    def test_create_announcement_empty_title(self):
        from services import create_announcement
        aid, err = create_announcement("   ", "Body text", "admin_user")
        self.assertIsNone(aid)
        self.assertIn("Title", err)

    def test_create_announcement_empty_body(self):
        from services import create_announcement
        aid, err = create_announcement("Title", "   ", "admin_user")
        self.assertIsNone(aid)
        self.assertIn("Body", err)

    def test_create_announcement_no_db(self):
        from services import create_announcement
        with patch("services._get_db", return_value=None):
            aid, err = create_announcement("Title", "Body", "admin_user")
        self.assertIsNone(aid)
        self.assertIn("Database", err)

    def test_create_announcement_truncates_title(self):
        from services import create_announcement
        conn, cur = _make_conn(fetchone_val=(1,))
        with patch("services._get_db", return_value=conn):
            create_announcement("x" * 300, "Body", "admin_user")
        args = cur.execute.call_args[0][1]
        self.assertEqual(len(args[0]), 200)

    def test_create_announcement_with_pinned_and_expiry(self):
        from services import create_announcement
        conn, cur = _make_conn(fetchone_val=(5,))
        with patch("services._get_db", return_value=conn):
            aid, err = create_announcement("Pin me", "Body", "admin_user",
                                           pinned=True, expires_at="2026-12-31")
        self.assertIsNone(err)
        self.assertEqual(aid, 5)
        args = cur.execute.call_args[0][1]
        self.assertTrue(args[3])   # pinned=True
        self.assertEqual(args[4], "2026-12-31")

    def test_get_announcements_returns_list(self):
        from services import get_announcements
        now = datetime(2026, 6, 9, 12, 0)
        conn, cur = _make_conn(rows=[(1, "Test", "Body", "admin", False, True, None, now)])
        with patch("services._get_db", return_value=conn):
            items, err = get_announcements(active_only=True)
        self.assertIsNone(err)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Test")

    def test_get_announcements_no_db(self):
        from services import get_announcements
        with patch("services._get_db", return_value=None):
            items, err = get_announcements()
        self.assertEqual(items, [])
        self.assertIn("Database", err)

    def test_get_announcements_serializes_dates(self):
        from services import get_announcements
        now = datetime(2026, 6, 9, 12, 0)
        conn, cur = _make_conn(rows=[(1, "T", "B", "a", False, True, now, now)])
        with patch("services._get_db", return_value=conn):
            items, err = get_announcements()
        self.assertIsInstance(items[0]["created_at"], str)
        self.assertIsInstance(items[0]["expires_at"], str)

    def test_deactivate_announcement_success(self):
        from services import deactivate_announcement
        conn, cur = _make_conn(rowcount=1)
        with patch("services._get_db", return_value=conn):
            ok, err = deactivate_announcement(1, "mod_user")
        self.assertTrue(ok)
        self.assertIsNone(err)
        conn.commit.assert_called_once()

    def test_deactivate_announcement_not_found(self):
        from services import deactivate_announcement
        conn, cur = _make_conn(rowcount=0)
        with patch("services._get_db", return_value=conn):
            ok, err = deactivate_announcement(999, "mod_user")
        self.assertFalse(ok)
        self.assertIn("not found", err)

    def test_deactivate_announcement_no_db(self):
        from services import deactivate_announcement
        with patch("services._get_db", return_value=None):
            ok, err = deactivate_announcement(1, "mod_user")
        self.assertFalse(ok)
        self.assertIn("Database", err)


# =============================================================================
# Community health service tests
# =============================================================================

class CommunityHealthServiceTests(unittest.TestCase):

    def _make_health_conn(self):
        cur = MagicMock()
        # Queries: loans row, verif_requests, verif_approvals, active_users, feedback_count
        cur.fetchone.side_effect = [
            (5, 3, 10, 1, 2),   # loan stats tuple
            (4,),                # verif_requests
            (2,),                # verif_approvals
            (15,),               # active_users
            (7,),                # feedback_count
        ]
        conn = MagicMock()
        conn.cursor.return_value = cur
        return conn, cur

    def test_get_community_health_returns_dict(self):
        from services import get_community_health
        conn, _ = self._make_health_conn()
        with patch("services._get_db", return_value=conn):
            health, err = get_community_health(30)
        self.assertIsNone(err)
        self.assertEqual(health["period_days"], 30)
        self.assertIn("loans", health)
        self.assertIn("verifications", health)
        self.assertIn("users", health)
        self.assertIn("feedback", health)

    def test_get_community_health_7_day(self):
        from services import get_community_health
        conn, _ = self._make_health_conn()
        with patch("services._get_db", return_value=conn):
            health, err = get_community_health(7)
        self.assertEqual(health["period_days"], 7)

    def test_get_community_health_clamps_invalid_period(self):
        from services import get_community_health
        conn, _ = self._make_health_conn()
        with patch("services._get_db", return_value=conn):
            health, err = get_community_health(45)
        self.assertEqual(health["period_days"], 30)

    def test_get_community_health_no_db(self):
        from services import get_community_health
        with patch("services._get_db", return_value=None):
            health, err = get_community_health()
        self.assertIsNone(health)
        self.assertIn("Database", err)

    def test_get_community_health_loan_values(self):
        from services import get_community_health
        conn, _ = self._make_health_conn()
        with patch("services._get_db", return_value=conn):
            health, _ = get_community_health(30)
        self.assertEqual(health["loans"]["new"], 5)
        self.assertEqual(health["loans"]["repaid"], 3)
        self.assertEqual(health["loans"]["active"], 10)
        self.assertEqual(health["verifications"]["requests"], 4)
        self.assertEqual(health["users"]["active"], 15)


# =============================================================================
# Lender management service tests
# =============================================================================

class LenderManagementServiceTests(unittest.TestCase):

    def test_get_lender_management_list_returns_data(self):
        from services import get_lender_management_list
        now = datetime(2026, 6, 9)
        conn, cur = _make_conn(
            rows=[("alice", True, now, now, now, "u_alice", 5, 2, 0)],
            fetchone_val=(1,)
        )
        with patch("services._get_db", return_value=conn):
            items, total, err = get_lender_management_list()
        self.assertIsNone(err)
        self.assertEqual(total, 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["username"], "alice")

    def test_get_lender_management_list_no_db(self):
        from services import get_lender_management_list
        with patch("services._get_db", return_value=None):
            items, total, err = get_lender_management_list()
        self.assertEqual(items, [])
        self.assertEqual(total, 0)
        self.assertIn("Database", err)

    def test_get_lender_management_list_verified_filter(self):
        from services import get_lender_management_list
        conn, cur = _make_conn(rows=[], fetchone_val=(0,))
        with patch("services._get_db", return_value=conn):
            items, total, err = get_lender_management_list(verified_filter="verified")
        self.assertIsNone(err)
        # Check verified filter was applied in SQL
        sql = cur.execute.call_args_list[1][0][0]
        self.assertIn("verified_lender = TRUE", sql)

    def test_get_lender_management_list_search(self):
        from services import get_lender_management_list
        conn, cur = _make_conn(rows=[], fetchone_val=(0,))
        with patch("services._get_db", return_value=conn):
            get_lender_management_list(q="alice")
        params = cur.execute.call_args_list[0][0][1]
        self.assertIn("%alice%", params)

    def test_get_lender_management_list_serializes_dates(self):
        from services import get_lender_management_list
        now = datetime(2026, 6, 9, 12, 0)
        conn, cur = _make_conn(
            rows=[("alice", True, now, now, now, None, 0, 0, 0)],
            fetchone_val=(1,)
        )
        with patch("services._get_db", return_value=conn):
            items, _, _ = get_lender_management_list()
        self.assertIsInstance(items[0]["last_login"], str)


# =============================================================================
# Borrower activity service tests
# =============================================================================

class BorrowerActivityServiceTests(unittest.TestCase):

    def test_get_borrower_activity_list_returns_data(self):
        from services import get_borrower_activity_list
        now = datetime(2026, 6, 9)
        conn, cur = _make_conn(
            rows=[("bob", 3, "150.00", "100.00", 0, "0.00", now, False, 0)],
            fetchone_val=(1,)
        )
        with patch("services._get_db", return_value=conn):
            items, total, err = get_borrower_activity_list()
        self.assertIsNone(err)
        self.assertEqual(total, 1)
        self.assertEqual(items[0]["username"], "bob")

    def test_get_borrower_activity_list_no_db(self):
        from services import get_borrower_activity_list
        with patch("services._get_db", return_value=None):
            items, total, err = get_borrower_activity_list()
        self.assertEqual(items, [])
        self.assertEqual(total, 0)
        self.assertIn("Database", err)

    def test_get_borrower_activity_list_dispute_filter(self):
        from services import get_borrower_activity_list
        conn, cur = _make_conn(rows=[], fetchone_val=(0,))
        with patch("services._get_db", return_value=conn):
            get_borrower_activity_list(has_disputes=True)
        sql = cur.execute.call_args_list[0][0][0]
        self.assertIn("unpaid_loans > 0", sql)

    def test_get_borrower_activity_list_search(self):
        from services import get_borrower_activity_list
        conn, cur = _make_conn(rows=[], fetchone_val=(0,))
        with patch("services._get_db", return_value=conn):
            get_borrower_activity_list(q="bob")
        params = cur.execute.call_args_list[0][0][1]
        self.assertIn("%bob%", params)


# =============================================================================
# Audit investigation summary service tests
# =============================================================================

class AuditInvestigationServiceTests(unittest.TestCase):

    def _make_inv_conn(self):
        now = datetime(2026, 6, 9, 12, 0)
        cur = MagicMock()
        cur.fetchone.return_value = ("alice", "lender", True, now, now, now, "u_alice")
        cur.fetchall.return_value = []
        conn = MagicMock()
        conn.cursor.return_value = cur
        return conn, cur

    def test_get_audit_investigation_summary_returns_bundle(self):
        from services import get_audit_investigation_summary
        conn, _ = self._make_inv_conn()
        with patch("services._get_db", return_value=conn):
            summary, err = get_audit_investigation_summary("alice")
        self.assertIsNone(err)
        self.assertIn("user_record", summary)
        self.assertIn("lender_loans", summary)
        self.assertIn("borrower_loans", summary)
        self.assertIn("verifications", summary)
        self.assertIn("audit_actions", summary)

    def test_get_audit_investigation_summary_no_db(self):
        from services import get_audit_investigation_summary
        with patch("services._get_db", return_value=None):
            summary, err = get_audit_investigation_summary("alice")
        self.assertIsNone(summary)
        self.assertIn("Database", err)

    def test_get_audit_investigation_summary_unknown_user(self):
        from services import get_audit_investigation_summary
        cur = MagicMock()
        cur.fetchone.return_value = None
        cur.fetchall.return_value = []
        conn = MagicMock()
        conn.cursor.return_value = cur
        with patch("services._get_db", return_value=conn):
            summary, err = get_audit_investigation_summary("ghost")
        self.assertIsNone(err)
        self.assertIsNone(summary["user_record"])

    def test_get_audit_investigation_summary_serializes_dates(self):
        from services import get_audit_investigation_summary
        conn, _ = self._make_inv_conn()
        with patch("services._get_db", return_value=conn):
            summary, _ = get_audit_investigation_summary("alice")
        u = summary["user_record"]
        self.assertIsInstance(u["last_login"], str)
        self.assertIsInstance(u["created_at"], str)


# =============================================================================
# Mod queue service tests
# =============================================================================

class ModQueueServiceTests(unittest.TestCase):

    def test_get_mod_queue_returns_dict(self):
        from services import get_mod_queue
        now = datetime(2026, 6, 9, 12, 0)
        cur = MagicMock()
        cur.fetchall.side_effect = [
            [(1, "alice", "lender", "note", now)],             # verif (5 cols)
            [(101, "alice", "bob", "150.00", "USD", now)],     # disputes (6 cols)
            [(201, "alice", "bug", "Title", now)],             # feedback (5 cols)
        ]
        conn = MagicMock()
        conn.cursor.return_value = cur
        with patch("services._get_db", return_value=conn):
            queue, err = get_mod_queue()
        self.assertIsNone(err)
        self.assertIn("verifications", queue)
        self.assertIn("disputes", queue)
        self.assertIn("feedback", queue)
        self.assertIn("totals", queue)

    def test_get_mod_queue_no_db(self):
        from services import get_mod_queue
        with patch("services._get_db", return_value=None):
            queue, err = get_mod_queue()
        self.assertIsNone(queue)
        self.assertIn("Database", err)

    def test_get_mod_queue_totals_count(self):
        from services import get_mod_queue
        cur = MagicMock()
        now = datetime(2026, 6, 9, 12, 0)
        cur.fetchall.side_effect = [
            [(1, "alice", "lender", "note", now),
             (2, "bob",   "lender", "note", now)],   # 2 verifs (5 cols)
            [(101, "a", "b", "100", "USD", now)],    # 1 dispute (6 cols)
            [],                                       # 0 feedback
        ]
        conn = MagicMock()
        conn.cursor.return_value = cur
        with patch("services._get_db", return_value=conn):
            queue, _ = get_mod_queue()
        self.assertEqual(queue["totals"]["total"], 3)


# =============================================================================
# API route tests
# =============================================================================

def _make_app():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'api'))
    from app import app
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"
    return app


def _mod_session(client):
    with client.session_transaction() as sess:
        sess["username"] = "mod_user"
        sess["role"]     = "mod"


def _admin_session(client):
    with client.session_transaction() as sess:
        sess["username"] = "admin_user"
        sess["role"]     = "admin"


class AnnouncementsAPITests(unittest.TestCase):

    def setUp(self):
        self.app    = _make_app()
        self.client = self.app.test_client()

    def test_get_public_announcements(self):
        with patch("services.get_announcements", return_value=([], None)):
            res = self.client.get("/api/announcements")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("announcements", data)

    def test_get_admin_announcements_requires_auth(self):
        res = self.client.get("/api/admin/announcements")
        self.assertIn(res.status_code, (401, 403))

    def test_get_admin_announcements_mod(self):
        _mod_session(self.client)
        with patch("services.get_announcements", return_value=([], None)):
            res = self.client.get("/api/admin/announcements")
        self.assertEqual(res.status_code, 200)

    def test_create_announcement_mod(self):
        _mod_session(self.client)
        with patch("services.create_announcement", return_value=(1, None)):
            res = self.client.post("/api/admin/announcements",
                                   json={"title": "Hello", "body": "World"})
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.get_json()["id"], 1)

    def test_create_announcement_missing_title(self):
        _mod_session(self.client)
        res = self.client.post("/api/admin/announcements", json={"body": "no title"})
        self.assertEqual(res.status_code, 400)

    def test_create_announcement_service_error(self):
        _mod_session(self.client)
        with patch("services.create_announcement", return_value=(None, "DB error")):
            res = self.client.post("/api/admin/announcements",
                                   json={"title": "X", "body": "Y"})
        self.assertEqual(res.status_code, 400)

    def test_delete_announcement_mod(self):
        _mod_session(self.client)
        with patch("services.deactivate_announcement", return_value=(True, None)):
            res = self.client.delete("/api/admin/announcements/1")
        self.assertEqual(res.status_code, 200)

    def test_delete_announcement_not_found(self):
        _mod_session(self.client)
        with patch("services.deactivate_announcement", return_value=(False, "Announcement not found")):
            res = self.client.delete("/api/admin/announcements/999")
        self.assertEqual(res.status_code, 400)

    def test_delete_announcement_requires_auth(self):
        res = self.client.delete("/api/admin/announcements/1")
        self.assertIn(res.status_code, (401, 403))


class CommunityHealthAPITests(unittest.TestCase):

    def setUp(self):
        self.app    = _make_app()
        self.client = self.app.test_client()

    def test_api_community_health_requires_auth(self):
        res = self.client.get("/api/admin/health")
        self.assertIn(res.status_code, (401, 403))

    def test_api_community_health_mod(self):
        _mod_session(self.client)
        health = {"period_days": 30, "loans": {}, "verifications": {}, "users": {}, "feedback": {}}
        with patch("services.get_community_health", return_value=(health, None)):
            res = self.client.get("/api/admin/health?period=30")
        self.assertEqual(res.status_code, 200)
        self.assertIn("period_days", res.get_json())

    def test_api_community_health_clamps_period(self):
        _mod_session(self.client)
        health = {"period_days": 30, "loans": {}, "verifications": {}, "users": {}, "feedback": {}}
        with patch("services.get_community_health", return_value=(health, None)) as mock_fn:
            self.client.get("/api/admin/health?period=45")
        called_period = mock_fn.call_args[0][0]
        self.assertIn(called_period, (7, 30, 90))

    def test_api_community_health_page_mod(self):
        _mod_session(self.client)
        res = self.client.get("/admin/health")
        self.assertEqual(res.status_code, 200)


class ModQueueAPITests(unittest.TestCase):

    def setUp(self):
        self.app    = _make_app()
        self.client = self.app.test_client()

    def test_api_mod_queue_requires_auth(self):
        res = self.client.get("/api/mod/queue")
        self.assertIn(res.status_code, (401, 403))

    def test_api_mod_queue_mod(self):
        _mod_session(self.client)
        queue = {"verifications": [], "disputes": [], "feedback": [], "totals": {"total": 0}}
        with patch("services.get_mod_queue", return_value=(queue, None)):
            res = self.client.get("/api/mod/queue")
        self.assertEqual(res.status_code, 200)
        self.assertIn("verifications", res.get_json())

    def test_mod_queue_page_mod(self):
        _mod_session(self.client)
        res = self.client.get("/mod/queue")
        self.assertEqual(res.status_code, 200)

    def test_mod_queue_page_borrower_forbidden(self):
        with self.client.session_transaction() as sess:
            sess["username"] = "borrower_user"
            sess["role"]     = "borrower"
        res = self.client.get("/mod/queue")
        self.assertIn(res.status_code, (302, 403))


class LenderManagementAPITests(unittest.TestCase):

    def setUp(self):
        self.app    = _make_app()
        self.client = self.app.test_client()

    def test_api_lender_management_requires_auth(self):
        res = self.client.get("/api/admin/lenders/management")
        self.assertIn(res.status_code, (401, 403))

    def test_api_lender_management_mod(self):
        _mod_session(self.client)
        with patch("services.get_lender_management_list", return_value=([], 0, None)):
            res = self.client.get("/api/admin/lenders/management")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("lenders", data)
        self.assertIn("total", data)

    def test_lender_management_page_mod(self):
        _mod_session(self.client)
        res = self.client.get("/admin/lenders/management")
        self.assertEqual(res.status_code, 200)

    def test_lender_management_page_borrower_forbidden(self):
        with self.client.session_transaction() as sess:
            sess["username"] = "borrower_user"
            sess["role"]     = "borrower"
        res = self.client.get("/admin/lenders/management")
        self.assertIn(res.status_code, (302, 403))


class BorrowerActivityAPITests(unittest.TestCase):

    def setUp(self):
        self.app    = _make_app()
        self.client = self.app.test_client()

    def test_api_borrower_activity_requires_auth(self):
        res = self.client.get("/api/admin/borrowers")
        self.assertIn(res.status_code, (401, 403))

    def test_api_borrower_activity_mod(self):
        _mod_session(self.client)
        with patch("services.get_borrower_activity_list", return_value=([], 0, None)):
            res = self.client.get("/api/admin/borrowers")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("borrowers", data)

    def test_borrower_activity_page_mod(self):
        _mod_session(self.client)
        res = self.client.get("/admin/borrowers")
        self.assertEqual(res.status_code, 200)

    def test_borrower_activity_page_lender_forbidden(self):
        with self.client.session_transaction() as sess:
            sess["username"] = "lender_user"
            sess["role"]     = "lender"
        res = self.client.get("/admin/borrowers")
        self.assertIn(res.status_code, (302, 403))


class AuditInvestigationAPITests(unittest.TestCase):

    def setUp(self):
        self.app    = _make_app()
        self.client = self.app.test_client()

    def test_api_audit_summary_requires_auth(self):
        res = self.client.get("/api/audit/user/alice/summary")
        self.assertIn(res.status_code, (401, 403))

    def test_api_audit_summary_mod(self):
        _mod_session(self.client)
        bundle = {
            "user_record": {"username": "alice", "role": "lender"},
            "lender_loans": [],
            "borrower_loans": [],
            "verifications": [],
            "audit_actions": [],
        }
        with patch("services.get_audit_investigation_summary", return_value=(bundle, None)):
            res = self.client.get("/api/audit/user/alice/summary")
        self.assertEqual(res.status_code, 200)
        self.assertIn("user_record", res.get_json())

    def test_api_audit_summary_service_error(self):
        _mod_session(self.client)
        with patch("services.get_audit_investigation_summary", return_value=(None, "DB error")):
            res = self.client.get("/api/audit/user/alice/summary")
        self.assertEqual(res.status_code, 500)


# =============================================================================
# Page smoke tests
# =============================================================================

class Sprint10PageSmokeTests(unittest.TestCase):

    def setUp(self):
        self.app    = _make_app()
        self.client = self.app.test_client()

    def test_audit_user_page_mod(self):
        _mod_session(self.client)
        with patch("services.get_user_activity_timeline", return_value=([], None)):
            res = self.client.get("/audit/user/alice")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Investigation", res.data)

    def test_community_health_page_mod(self):
        _mod_session(self.client)
        res = self.client.get("/admin/health")
        self.assertEqual(res.status_code, 200)

    def test_lender_management_page_mod(self):
        _mod_session(self.client)
        res = self.client.get("/admin/lenders/management")
        self.assertEqual(res.status_code, 200)

    def test_admin_borrowers_page_mod(self):
        _mod_session(self.client)
        res = self.client.get("/admin/borrowers")
        self.assertEqual(res.status_code, 200)

    def test_mod_queue_page_mod(self):
        _mod_session(self.client)
        res = self.client.get("/mod/queue")
        self.assertEqual(res.status_code, 200)


if __name__ == "__main__":
    unittest.main()
