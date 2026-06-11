"""Tests for Request System Expansion Sprint (Tasks 1-10)."""
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, date
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))


# ---------------------------------------------------------------------------
# log_request_event
# ---------------------------------------------------------------------------

class LogRequestEventTests(unittest.TestCase):

    @patch("services._get_db")
    @patch("services._ensure_request_events_table")
    def test_inserts_event(self, mock_ensure, mock_db):
        from services import log_request_event
        conn = MagicMock(); cur = MagicMock()
        cur.fetchone.return_value = (7,)
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        eid, err = log_request_event("REQ-TEST0001", "created", actor="alice", note="hi")
        self.assertIsNone(err)
        self.assertEqual(eid, 7)
        conn.commit.assert_called()

    @patch("services._get_db")
    def test_db_failure(self, mock_db):
        from services import log_request_event
        mock_db.return_value = None
        eid, err = log_request_event("REQ-X", "created")
        self.assertIsNone(eid)
        self.assertIn("Database", err)

    @patch("services._get_db")
    @patch("services._ensure_request_events_table")
    def test_actor_and_note_optional(self, mock_ensure, mock_db):
        from services import log_request_event
        conn = MagicMock(); cur = MagicMock()
        cur.fetchone.return_value = (1,)
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        eid, err = log_request_event("REQ-TEST0001", "expired")
        self.assertIsNone(err)
        args = cur.execute.call_args[0][1]
        self.assertIsNone(args[2])   # actor
        self.assertIsNone(args[3])   # note


# ---------------------------------------------------------------------------
# get_request_events
# ---------------------------------------------------------------------------

class GetRequestEventsTests(unittest.TestCase):

    @patch("services._get_db")
    @patch("services._ensure_request_events_table")
    def test_returns_events_list(self, mock_ensure, mock_db):
        from services import get_request_events
        conn = MagicMock(); cur = MagicMock()
        cur.fetchall.return_value = [
            (1, "created",      "alice", "Request created", datetime(2026,6,1,10,0)),
            (2, "status_changed", "mod", "Status → funded", datetime(2026,6,5,12,0)),
        ]
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        events, err = get_request_events("REQ-TEST0001")
        self.assertIsNone(err)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["event_type"], "created")
        self.assertEqual(events[1]["event_type"], "status_changed")

    @patch("services._get_db")
    @patch("services._ensure_request_events_table")
    def test_empty_returns_empty_list(self, mock_ensure, mock_db):
        from services import get_request_events
        conn = MagicMock(); cur = MagicMock()
        cur.fetchall.return_value = []
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        events, err = get_request_events("REQ-NONE")
        self.assertIsNone(err)
        self.assertEqual(events, [])

    @patch("services._get_db")
    def test_db_failure(self, mock_db):
        from services import get_request_events
        mock_db.return_value = None
        events, err = get_request_events("REQ-X")
        self.assertEqual(events, [])
        self.assertIn("Database", err)


# ---------------------------------------------------------------------------
# find_duplicate_loan_requests
# ---------------------------------------------------------------------------

class FindDuplicateLoanRequestsTests(unittest.TestCase):

    @patch("services._get_db")
    @patch("services._ensure_loan_requests_table")
    def test_finds_duplicates(self, mock_ensure, mock_db):
        from services import find_duplicate_loan_requests
        conn = MagicMock(); cur = MagicMock()
        cur.fetchall.return_value = [
            ("REQ-OTHER001", "open", datetime(2026,6,2), 100.00),
        ]
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        dupes, err = find_duplicate_loan_requests("alice", days=10)
        self.assertIsNone(err)
        self.assertEqual(len(dupes), 1)
        self.assertEqual(dupes[0]["request_id"], "REQ-OTHER001")

    @patch("services._get_db")
    @patch("services._ensure_loan_requests_table")
    def test_exclude_request_id(self, mock_ensure, mock_db):
        from services import find_duplicate_loan_requests
        conn = MagicMock(); cur = MagicMock()
        cur.fetchall.return_value = []
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        dupes, err = find_duplicate_loan_requests("alice", exclude_request_id="REQ-SELF001")
        self.assertIsNone(err)
        sql = cur.execute.call_args[0][0]
        self.assertIn("request_id != %s", sql)

    @patch("services._get_db")
    @patch("services._ensure_loan_requests_table")
    def test_no_duplicates_returns_empty(self, mock_ensure, mock_db):
        from services import find_duplicate_loan_requests
        conn = MagicMock(); cur = MagicMock()
        cur.fetchall.return_value = []
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        dupes, err = find_duplicate_loan_requests("bob")
        self.assertIsNone(err)
        self.assertEqual(dupes, [])

    def test_blank_username_returns_error(self):
        from services import find_duplicate_loan_requests
        dupes, err = find_duplicate_loan_requests("")
        self.assertEqual(dupes, [])
        self.assertIsNotNone(err)

    @patch("services._get_db")
    def test_db_failure(self, mock_db):
        from services import find_duplicate_loan_requests
        mock_db.return_value = None
        dupes, err = find_duplicate_loan_requests("alice")
        self.assertEqual(dupes, [])
        self.assertIn("Database", err)


# ---------------------------------------------------------------------------
# API: events endpoint
# ---------------------------------------------------------------------------

class RequestEventsAPITests(unittest.TestCase):

    def setUp(self):
        import app as flask_app
        flask_app.app.config["TESTING"] = True
        flask_app.app.config["SECRET_KEY"] = "test"
        self.client = flask_app.app.test_client()

    def _session(self, username="alice", role="borrower"):
        with self.client.session_transaction() as s:
            s["username"] = username
            s["role"] = role
            s["perm_version"] = 0

    def _mod(self):
        self._session("moduser", "mod")

    def test_events_requires_auth(self):
        r = self.client.get("/api/loan-requests/REQ-TEST0001/events")
        self.assertIn(r.status_code, (401, 403))

    @patch("services.get_request_events", return_value=([], None))
    @patch("services.get_loan_request", return_value=(
        {"request_id": "REQ-TEST0001", "borrower_username": "alice",
         "request_status": "open", "requested_amount": None,
         "requested_repayment_amount": None, "requested_due_date": None,
         "thread_url": None, "reddit_post_id": None, "reddit_comment_id": None,
         "reddit_username": None, "created_at": "2026-06-01T00:00:00",
         "updated_at": "2026-06-01T00:00:00", "funded_loan_id": None,
         "notes": None, "funded_loan_ref": None}, None))
    def test_borrower_sees_own_events(self, mock_get, mock_events):
        self._session("alice", "borrower")
        r = self.client.get("/api/loan-requests/REQ-TEST0001/events")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"events", r.data)

    @patch("services.get_loan_request", return_value=(
        {"request_id": "REQ-TEST0001", "borrower_username": "bob",
         "request_status": "open", "requested_amount": None,
         "requested_repayment_amount": None, "requested_due_date": None,
         "thread_url": None, "reddit_post_id": None, "reddit_comment_id": None,
         "reddit_username": None, "created_at": "2026-06-01T00:00:00",
         "updated_at": "2026-06-01T00:00:00", "funded_loan_id": None,
         "notes": None, "funded_loan_ref": None}, None))
    def test_borrower_cannot_see_others_events(self, mock_get):
        self._session("alice", "borrower")
        r = self.client.get("/api/loan-requests/REQ-TEST0001/events")
        self.assertIn(r.status_code, (403, 404))

    @patch("services.get_request_events", return_value=([
        {"id": 1, "event_type": "created", "actor": "alice",
         "note": "created", "created_at": "2026-06-01 10:00:00"}
    ], None))
    def test_mod_sees_any_events(self, mock_events):
        self._mod()
        r = self.client.get("/api/loan-requests/REQ-TEST0001/events")
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertEqual(len(d["events"]), 1)

    @patch("services.get_request_events", return_value=([], "db error"))
    def test_events_db_error_returns_500(self, mock_events):
        self._mod()
        r = self.client.get("/api/loan-requests/REQ-TEST0001/events")
        self.assertEqual(r.status_code, 500)


# ---------------------------------------------------------------------------
# API: duplicates endpoint
# ---------------------------------------------------------------------------

class RequestDuplicatesAPITests(unittest.TestCase):

    def setUp(self):
        import app as flask_app
        flask_app.app.config["TESTING"] = True
        flask_app.app.config["SECRET_KEY"] = "test"
        self.client = flask_app.app.test_client()

    def _mod(self):
        with self.client.session_transaction() as s:
            s["username"] = "moduser"
            s["role"] = "mod"
            s["perm_version"] = 0

    def test_requires_mod(self):
        with self.client.session_transaction() as s:
            s["username"] = "alice"
            s["role"] = "borrower"
            s["perm_version"] = 0
        r = self.client.get("/api/loan-requests/REQ-TEST0001/duplicates")
        self.assertIn(r.status_code, (401, 403))

    @patch("services.find_duplicate_loan_requests", return_value=([], None))
    @patch("services.get_loan_request", return_value=(
        {"request_id": "REQ-TEST0001", "borrower_username": "alice",
         "request_status": "open"}, None))
    def test_no_duplicates(self, mock_get, mock_dupes):
        self._mod()
        r = self.client.get("/api/loan-requests/REQ-TEST0001/duplicates")
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertEqual(d["duplicates"], [])
        self.assertEqual(d["borrower"], "alice")

    @patch("services.find_duplicate_loan_requests", return_value=([
        {"request_id": "REQ-OTHER001", "request_status": "open",
         "created_at": "2026-06-05", "requested_amount": 100.0}
    ], None))
    @patch("services.get_loan_request", return_value=(
        {"request_id": "REQ-TEST0001", "borrower_username": "alice",
         "request_status": "open"}, None))
    def test_found_duplicates(self, mock_get, mock_dupes):
        self._mod()
        r = self.client.get("/api/loan-requests/REQ-TEST0001/duplicates")
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertEqual(len(d["duplicates"]), 1)

    @patch("services.get_loan_request", return_value=(None, "Request not found"))
    def test_not_found_returns_404(self, mock_get):
        self._mod()
        r = self.client.get("/api/loan-requests/REQ-GHOST/duplicates")
        self.assertEqual(r.status_code, 404)


# ---------------------------------------------------------------------------
# API: analytics page route
# ---------------------------------------------------------------------------

class RequestAnalyticsPageTests(unittest.TestCase):

    def setUp(self):
        import app as flask_app
        flask_app.app.config["TESTING"] = True
        flask_app.app.config["SECRET_KEY"] = "test"
        self.client = flask_app.app.test_client()

    def _admin(self):
        with self.client.session_transaction() as s:
            s["username"] = "testadmin"
            s["role"] = "admin"
            s["perm_version"] = 0

    def test_requires_admin(self):
        with self.client.session_transaction() as s:
            s["username"] = "moduser"
            s["role"] = "mod"
            s["perm_version"] = 0
        r = self.client.get("/admin/request-analytics")
        self.assertIn(r.status_code, (302, 403))

    def test_admin_renders(self):
        self._admin()
        r = self.client.get("/admin/request-analytics")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Request Analytics", r.data)
        self.assertIn(b"EXPIRATION", r.data)


# ---------------------------------------------------------------------------
# Event logging wired into status-change and link routes
# ---------------------------------------------------------------------------

class EventLoggingIntegrationTests(unittest.TestCase):

    def setUp(self):
        import app as flask_app
        flask_app.app.config["TESTING"] = True
        flask_app.app.config["SECRET_KEY"] = "test"
        self.client = flask_app.app.test_client()
        with self.client.session_transaction() as s:
            s["username"] = "moduser"
            s["role"] = "mod"
            s["perm_version"] = 0

    @patch("services.log_request_event", return_value=(1, None))
    @patch("services.log_audit")
    @patch("services.update_request_status", return_value=(True, None))
    def test_status_change_logs_event(self, mock_upd, mock_audit, mock_log_event):
        r = self.client.patch("/api/loan-requests/REQ-TEST0001/status",
                              json={"status": "expired", "note": "too old"})
        self.assertEqual(r.status_code, 200)
        mock_log_event.assert_called_once()
        call_args = mock_log_event.call_args[0]
        self.assertEqual(call_args[0], "REQ-TEST0001")
        self.assertEqual(call_args[1], "status_changed")

    @patch("services.log_request_event", return_value=(2, None))
    @patch("services.log_audit")
    @patch("services.link_request_to_loan", return_value=(True, None))
    def test_link_logs_event(self, mock_link, mock_audit, mock_log_event):
        r = self.client.post("/api/loan-requests/REQ-TEST0001/link",
                             json={"loan_db_id": 42})
        self.assertEqual(r.status_code, 200)
        mock_log_event.assert_called_once()
        call_args = mock_log_event.call_args[0]
        self.assertEqual(call_args[0], "REQ-TEST0001")
        self.assertEqual(call_args[1], "linked_to_loan")

    @patch("services.log_request_event", return_value=(3, None))
    @patch("services.find_duplicate_loan_requests", return_value=([], None))
    @patch("services.create_loan_request", return_value=("REQ-NEW00001", None))
    def test_create_logs_event(self, mock_create, mock_dupes, mock_log_event):
        r = self.client.post("/api/loan-requests",
                             json={"borrower_username": "moduser"})
        self.assertEqual(r.status_code, 201)
        mock_log_event.assert_called_once()
        call_args = mock_log_event.call_args[0]
        self.assertEqual(call_args[1], "created")

    @patch("services.log_request_event", return_value=(4, None))
    @patch("services.find_duplicate_loan_requests", return_value=([
        {"request_id": "REQ-OLD0001", "request_status": "open",
         "created_at": "2026-06-01", "requested_amount": 100.0}
    ], None))
    @patch("services.create_loan_request", return_value=("REQ-NEW00002", None))
    def test_create_returns_possible_duplicate_flag(self, mock_create, mock_dupes, mock_log_event):
        r = self.client.post("/api/loan-requests",
                             json={"borrower_username": "moduser"})
        self.assertEqual(r.status_code, 201)
        d = r.get_json()
        self.assertTrue(d["possible_duplicate"])


# ---------------------------------------------------------------------------
# Queue duplicate flag in response
# ---------------------------------------------------------------------------

class QueueDuplicateFlagTests(unittest.TestCase):

    def setUp(self):
        import app as flask_app
        flask_app.app.config["TESTING"] = True
        flask_app.app.config["SECRET_KEY"] = "test"
        self.client = flask_app.app.test_client()
        with self.client.session_transaction() as s:
            s["username"] = "moduser"
            s["role"] = "mod"
            s["perm_version"] = 0

    @patch("services.get_loan_request_queue", return_value=([
        {"id": 1, "request_id": "REQ-A", "borrower_username": "alice",
         "reddit_username": None, "requested_amount": 100.0,
         "request_status": "open", "thread_url": None,
         "created_at": "2026-06-01", "requested_due_date": None,
         "funded_loan_ref": None, "possible_duplicate": True},
    ], 1, None))
    def test_queue_includes_possible_duplicate_field(self, mock_q):
        r = self.client.get("/api/loan-requests")
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertTrue(d["requests"][0]["possible_duplicate"])

    @patch("services.get_loan_request_queue", return_value=([
        {"id": 2, "request_id": "REQ-B", "borrower_username": "bob",
         "reddit_username": None, "requested_amount": 50.0,
         "request_status": "open", "thread_url": None,
         "created_at": "2026-06-01", "requested_due_date": None,
         "funded_loan_ref": None, "possible_duplicate": False},
    ], 1, None))
    def test_queue_false_when_no_duplicate(self, mock_q):
        r = self.client.get("/api/loan-requests")
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertFalse(d["requests"][0]["possible_duplicate"])


# ---------------------------------------------------------------------------
# Global search — requests type
# ---------------------------------------------------------------------------

class GlobalSearchRequestsTests(unittest.TestCase):

    def setUp(self):
        import app as flask_app
        flask_app.app.config["TESTING"] = True
        flask_app.app.config["SECRET_KEY"] = "test"
        self.client = flask_app.app.test_client()
        with self.client.session_transaction() as s:
            s["username"] = "moduser"
            s["role"] = "mod"
            s["perm_version"] = 0

    @patch("services.search_loan_requests", return_value=([
        {"request_id": "REQ-SRCH001", "borrower_username": "alice",
         "requested_amount": 100.0, "request_status": "open",
         "thread_url": None, "created_at": "2026-06-01"}
    ], 1, None))
    def test_search_endpoint_returns_results(self, mock_search):
        r = self.client.get("/api/loan-requests/search?q=alice")
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertEqual(len(d["results"]), 1)
        self.assertEqual(d["results"][0]["request_id"], "REQ-SRCH001")

    def test_global_search_page_renders(self):
        r = self.client.get("/dashboard/admin/search")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"requests", r.data.lower())

    def test_search_requires_mod(self):
        with self.client.session_transaction() as s:
            s["username"] = "alice"
            s["role"] = "borrower"
            s["perm_version"] = 0
        r = self.client.get("/api/loan-requests/search?q=alice")
        self.assertIn(r.status_code, (401, 403))


# ---------------------------------------------------------------------------
# Permission checks (Task 10)
# ---------------------------------------------------------------------------

class PermissionTests(unittest.TestCase):

    def setUp(self):
        import app as flask_app
        flask_app.app.config["TESTING"] = True
        flask_app.app.config["SECRET_KEY"] = "test"
        self.client = flask_app.app.test_client()

    def test_analytics_page_blocks_non_admin(self):
        for role in ("borrower", "lender", "mod"):
            with self.client.session_transaction() as s:
                s["username"] = "user"
                s["role"] = role
                s["perm_version"] = 0
            r = self.client.get("/admin/request-analytics")
            self.assertIn(r.status_code, (302, 403),
                          f"Role {role} should not access analytics page")

    def test_duplicates_endpoint_blocks_borrower(self):
        with self.client.session_transaction() as s:
            s["username"] = "alice"
            s["role"] = "borrower"
            s["perm_version"] = 0
        r = self.client.get("/api/loan-requests/REQ-X/duplicates")
        self.assertIn(r.status_code, (401, 403))

    def test_events_endpoint_blocks_unauthenticated(self):
        r = self.client.get("/api/loan-requests/REQ-X/events")
        self.assertIn(r.status_code, (401, 403))


if __name__ == "__main__":
    unittest.main()
