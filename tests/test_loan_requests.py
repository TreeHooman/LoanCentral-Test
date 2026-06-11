"""Tests for Loan Request Sprint: service functions and API endpoints."""
import unittest
from unittest.mock import patch, MagicMock
from datetime import date, datetime
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

from services import (
    _LR_STATUSES,
    _generate_request_id,
)


# ---------------------------------------------------------------------------
# _generate_request_id
# ---------------------------------------------------------------------------

class GenerateRequestIdTests(unittest.TestCase):

    def test_format_prefix(self):
        rid = _generate_request_id()
        self.assertTrue(rid.startswith("REQ-"), rid)

    def test_length(self):
        rid = _generate_request_id()
        self.assertEqual(len(rid), 12)  # "REQ-" + 8 chars

    def test_uppercase_alphanumeric(self):
        rid = _generate_request_id()
        suffix = rid[4:]
        self.assertTrue(suffix.isalnum() and suffix == suffix.upper(), rid)

    def test_uniqueness(self):
        ids = {_generate_request_id() for _ in range(50)}
        self.assertEqual(len(ids), 50)


# ---------------------------------------------------------------------------
# _LR_STATUSES constant
# ---------------------------------------------------------------------------

class LRStatusesTests(unittest.TestCase):

    def test_required_statuses_present(self):
        for s in ("open", "funded", "cancelled", "expired", "removed", "duplicate", "denied_by_mod"):
            self.assertIn(s, _LR_STATUSES)


# ---------------------------------------------------------------------------
# create_loan_request
# ---------------------------------------------------------------------------

class CreateLoanRequestTests(unittest.TestCase):

    def _make_conn(self):
        conn = MagicMock()
        cur  = MagicMock()
        # fetchone used for uniqueness check (returns None = no collision) + RETURNING id
        cur.fetchone.side_effect = [None, (1,)]
        conn.cursor.return_value  = cur
        return conn, cur

    @patch("services._get_db")
    @patch("services.log_event")
    def test_create_minimal(self, mock_log, mock_db):
        from services import create_loan_request
        conn, cur = self._make_conn()
        mock_db.return_value = conn
        req_id, err = create_loan_request("alice")
        self.assertIsNone(err)
        self.assertIsNotNone(req_id)
        self.assertTrue(req_id.startswith("REQ-"))
        conn.commit.assert_called()

    @patch("services._get_db")
    @patch("services.log_event")
    def test_create_with_all_fields(self, mock_log, mock_db):
        from services import create_loan_request
        conn, cur = self._make_conn()
        mock_db.return_value = conn
        req_id, err = create_loan_request(
            borrower_username="bob",
            reddit_username="bob_reddit",
            requested_amount=200.00,
            requested_repayment_amount=220.00,
            requested_due_date=date(2026, 7, 1),
            thread_url="https://reddit.com/r/borrow/comments/abc",
            reddit_post_id="abc123",
            reddit_comment_id="xyz456",
            notes="test note",
        )
        self.assertIsNone(err)
        self.assertIsNotNone(req_id)

    @patch("services._get_db")
    def test_db_failure_returns_error(self, mock_db):
        from services import create_loan_request
        mock_db.return_value = None
        req_id, err = create_loan_request("alice")
        self.assertIsNone(req_id)
        self.assertIn("Database", err)

    def test_blank_username_returns_error(self):
        from services import create_loan_request
        req_id, err = create_loan_request("")
        self.assertIsNone(req_id)
        self.assertIsNotNone(err)


# ---------------------------------------------------------------------------
# get_loan_request
# ---------------------------------------------------------------------------

class GetLoanRequestTests(unittest.TestCase):

    def _row(self, req_id="REQ-TEST1234"):
        return (
            1, req_id, "alice", "alice_r", 100.00, 110.00,
            date(2026, 7, 1), "open",
            "https://reddit.com/r/borrow/comments/x", "postid", "commid",
            datetime(2026, 6, 1), datetime(2026, 6, 1), None, "some note", None,
        )

    @patch("services._get_db")
    def test_found(self, mock_db):
        from services import get_loan_request
        conn = MagicMock(); cur = MagicMock()
        cur.fetchone.return_value = self._row()
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        req, err = get_loan_request("REQ-TEST1234")
        self.assertIsNone(err)
        self.assertEqual(req["request_id"], "REQ-TEST1234")
        self.assertEqual(req["borrower_username"], "alice")

    @patch("services._get_db")
    def test_not_found_returns_none(self, mock_db):
        from services import get_loan_request
        conn = MagicMock(); cur = MagicMock()
        cur.fetchone.return_value = None
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        req, err = get_loan_request("REQ-NOTEXIST")
        self.assertIsNone(req)
        self.assertIsNotNone(err)

    @patch("services._get_db")
    def test_db_failure(self, mock_db):
        from services import get_loan_request
        mock_db.return_value = None
        req, err = get_loan_request("REQ-X")
        self.assertIsNone(req)
        self.assertIn("Database", err)


# ---------------------------------------------------------------------------
# get_loan_requests_for_borrower
# ---------------------------------------------------------------------------

class GetBorrowerRequestsTests(unittest.TestCase):

    @patch("services._get_db")
    def test_returns_list(self, mock_db):
        from services import get_loan_requests_for_borrower
        conn = MagicMock(); cur = MagicMock()
        cur.fetchone.return_value = (2,)
        cur.fetchall.return_value = [
            (1, "REQ-AA000001", 100.00, "open", None, datetime(2026,6,1), None, None),
        ]
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        rows, total, err = get_loan_requests_for_borrower("alice")
        self.assertIsNone(err)
        self.assertEqual(total, 2)
        self.assertEqual(len(rows), 1)

    @patch("services._get_db")
    def test_db_failure(self, mock_db):
        from services import get_loan_requests_for_borrower
        mock_db.return_value = None
        rows, total, err = get_loan_requests_for_borrower("alice")
        self.assertEqual(rows, [])
        self.assertIn("Database", err)


# ---------------------------------------------------------------------------
# update_request_status
# ---------------------------------------------------------------------------

class UpdateRequestStatusTests(unittest.TestCase):

    @patch("services._get_db")
    @patch("services.log_audit")
    def test_valid_status_change(self, mock_audit, mock_db):
        from services import update_request_status
        conn = MagicMock(); cur = MagicMock()
        # fetchone: before + after status
        cur.fetchone.side_effect = [("open",), ("expired",)]
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        ok, err = update_request_status("REQ-X", "expired", "moduser")
        self.assertTrue(ok)
        self.assertIsNone(err)
        conn.commit.assert_called()

    def test_invalid_status_rejected(self):
        from services import update_request_status
        ok, err = update_request_status("REQ-X", "approved", "moduser")
        self.assertFalse(ok)
        self.assertIsNotNone(err)

    @patch("services._get_db")
    def test_db_failure(self, mock_db):
        from services import update_request_status
        mock_db.return_value = None
        ok, err = update_request_status("REQ-X", "expired", "mod")
        self.assertFalse(ok)
        self.assertIn("Database", err)


# ---------------------------------------------------------------------------
# link_request_to_loan
# ---------------------------------------------------------------------------

class LinkRequestToLoanTests(unittest.TestCase):

    @patch("services._get_db")
    @patch("services.log_event")
    def test_link_unlinked_request(self, mock_log, mock_db):
        from services import link_request_to_loan
        conn = MagicMock(); cur = MagicMock()
        cur.fetchone.return_value = (1, "open", None)
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        ok, err = link_request_to_loan("REQ-X", 42, "mod")
        self.assertTrue(ok)
        self.assertIsNone(err)

    @patch("services._get_db")
    @patch("services.log_event")
    def test_already_linked_without_override_rejected(self, mock_log, mock_db):
        from services import link_request_to_loan
        conn = MagicMock(); cur = MagicMock()
        cur.fetchone.return_value = (1, "funded", 99)
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        ok, err = link_request_to_loan("REQ-X", 42, "mod", override=False)
        self.assertFalse(ok)
        self.assertIsNotNone(err)

    @patch("services._get_db")
    @patch("services.log_event")
    def test_already_linked_with_override_succeeds(self, mock_log, mock_db):
        from services import link_request_to_loan
        conn = MagicMock(); cur = MagicMock()
        cur.fetchone.return_value = (1, "funded", 99)
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        ok, err = link_request_to_loan("REQ-X", 42, "mod", override=True)
        self.assertTrue(ok)
        self.assertIsNone(err)

    @patch("services._get_db")
    def test_db_failure(self, mock_db):
        from services import link_request_to_loan
        mock_db.return_value = None
        ok, err = link_request_to_loan("REQ-X", 1, "mod")
        self.assertFalse(ok)
        self.assertIn("Database", err)


# ---------------------------------------------------------------------------
# expire_old_requests
# ---------------------------------------------------------------------------

class ExpireOldRequestsTests(unittest.TestCase):

    @patch("services._get_db")
    def test_expire_returns_count(self, mock_db):
        from services import expire_old_requests
        conn = MagicMock(); cur = MagicMock()
        cur.rowcount = 3
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        n, err = expire_old_requests(days=10)
        self.assertIsNone(err)
        self.assertEqual(n, 3)
        conn.commit.assert_called()

    @patch("services._ensure_loan_requests_table")
    @patch("services._get_db")
    def test_dry_run_returns_count_no_commit(self, mock_db, mock_ensure):
        from services import expire_old_requests
        conn = MagicMock(); cur = MagicMock()
        cur.fetchone.return_value = (5,)
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        n, err = expire_old_requests(days=10, dry_run=True)
        self.assertIsNone(err)
        self.assertEqual(n, 5)
        conn.commit.assert_not_called()

    @patch("services._get_db")
    def test_db_failure(self, mock_db):
        from services import expire_old_requests
        mock_db.return_value = None
        n, err = expire_old_requests()
        self.assertEqual(n, 0)
        self.assertIsNotNone(err)


# ---------------------------------------------------------------------------
# get_request_analytics
# ---------------------------------------------------------------------------

class GetRequestAnalyticsTests(unittest.TestCase):

    @patch("services._get_db")
    def test_returns_analytics_dict(self, mock_db):
        from services import get_request_analytics
        conn = MagicMock(); cur = MagicMock()
        cur.fetchone.return_value = (10, 3, 5, 1, 1, 0, 0, 1500.00)
        cur.fetchall.return_value = []
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        data, err = get_request_analytics()
        self.assertIsNone(err)
        self.assertIn("total", data)
        self.assertIn("funded", data)
        self.assertIn("weekly", data)

    @patch("services._get_db")
    def test_db_failure(self, mock_db):
        from services import get_request_analytics
        mock_db.return_value = None
        data, err = get_request_analytics()
        self.assertIsNone(data)
        self.assertIn("Database", err)


# ---------------------------------------------------------------------------
# search_loan_requests  (returns rows, total, error)
# ---------------------------------------------------------------------------

class SearchLoanRequestsTests(unittest.TestCase):

    @patch("services._get_db")
    def test_search_returns_results(self, mock_db):
        from services import search_loan_requests
        conn = MagicMock(); cur = MagicMock()
        cur.fetchone.return_value = (1,)
        cur.fetchall.return_value = [
            ("REQ-SRCH0001", "alice", 100.00, "open", None, datetime(2026,6,1)),
        ]
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        rows, total, err = search_loan_requests(q="alice")
        self.assertIsNone(err)
        self.assertEqual(len(rows), 1)
        self.assertEqual(total, 1)

    @patch("services._get_db")
    def test_no_query_returns_all(self, mock_db):
        from services import search_loan_requests
        conn = MagicMock(); cur = MagicMock()
        cur.fetchone.return_value = (0,)
        cur.fetchall.return_value = []
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        rows, total, err = search_loan_requests()
        self.assertIsNone(err)
        self.assertEqual(rows, [])

    @patch("services._get_db")
    def test_db_failure(self, mock_db):
        from services import search_loan_requests
        mock_db.return_value = None
        rows, total, err = search_loan_requests(q="alice")
        self.assertEqual(rows, [])
        self.assertIsNotNone(err)


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

class LoanRequestAPITests(unittest.TestCase):

    def setUp(self):
        import app as flask_app
        flask_app.app.config["TESTING"] = True
        flask_app.app.config["SECRET_KEY"] = "test"
        self.client = flask_app.app.test_client()

    def _session(self, username="testuser", role="borrower"):
        with self.client.session_transaction() as s:
            s["username"] = username
            s["role"]     = role
            s["perm_version"] = 0

    def _mod_session(self):
        self._session("moduser", "mod")

    def _admin_session(self):
        self._session("testadmin", "admin")

    # ── auth guards ──────────────────────────────────────────────────────────

    def test_create_request_requires_auth(self):
        r = self.client.post("/api/loan-requests", json={"borrower_username": "x"})
        self.assertIn(r.status_code, (401, 403))

    def test_list_requests_requires_mod(self):
        self._session()
        r = self.client.get("/api/loan-requests")
        self.assertIn(r.status_code, (401, 403))

    def test_mine_requires_auth(self):
        r = self.client.get("/api/loan-requests/mine")
        self.assertIn(r.status_code, (401, 403))

    def test_update_status_requires_mod(self):
        self._session()
        r = self.client.patch("/api/loan-requests/REQ-TEST0001/status",
                               json={"status": "expired"})
        self.assertIn(r.status_code, (401, 403))

    def test_link_request_requires_mod(self):
        self._session()
        r = self.client.post("/api/loan-requests/REQ-TEST0001/link",
                              json={"loan_db_id": 1})
        self.assertIn(r.status_code, (401, 403))

    def test_analytics_requires_admin(self):
        self._mod_session()
        r = self.client.get("/api/admin/request-analytics")
        self.assertIn(r.status_code, (401, 403))

    def test_expire_requires_admin(self):
        self._mod_session()
        r = self.client.post("/api/admin/requests/expire", json={})
        self.assertIn(r.status_code, (401, 403))

    # ── functional ───────────────────────────────────────────────────────────

    @patch("services.create_loan_request", return_value=("REQ-NEW00001", None))
    def test_create_request_own_username(self, mock_create):
        self._session("alice", "borrower")
        r = self.client.post("/api/loan-requests",
                              json={"borrower_username": "alice", "requested_amount": 100})
        self.assertEqual(r.status_code, 201)
        d = r.get_json()
        self.assertIn("request_id", d)

    @patch("services.create_loan_request", return_value=(None, "some error"))
    def test_create_request_service_error(self, mock_create):
        self._session("alice", "borrower")
        r = self.client.post("/api/loan-requests",
                              json={"borrower_username": "alice"})
        self.assertIn(r.status_code, (400, 500))

    def test_create_request_other_user_forbidden(self):
        self._session("alice", "borrower")
        r = self.client.post("/api/loan-requests",
                              json={"borrower_username": "bob", "requested_amount": 100})
        self.assertIn(r.status_code, (403, 400))

    @patch("services.get_loan_requests_for_borrower", return_value=([], 0, None))
    def test_mine_returns_list(self, mock_mine):
        self._session("alice", "borrower")
        r = self.client.get("/api/loan-requests/mine")
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertIn("requests", d)

    @patch("services.get_loan_request_queue", return_value=([], 0, None))
    def test_list_requests_mod_ok(self, mock_q):
        self._mod_session()
        r = self.client.get("/api/loan-requests")
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertIn("requests", d)

    @patch("services.update_request_status", return_value=(True, None))
    def test_update_status_mod_ok(self, mock_upd):
        self._mod_session()
        r = self.client.patch("/api/loan-requests/REQ-TEST0001/status",
                               json={"status": "expired"})
        self.assertEqual(r.status_code, 200)

    @patch("services.update_request_status", return_value=(False, "Invalid status: approved"))
    def test_update_status_bad_value(self, mock_upd):
        self._mod_session()
        r = self.client.patch("/api/loan-requests/REQ-TEST0001/status",
                               json={"status": "approved"})
        self.assertEqual(r.status_code, 400)

    @patch("services.get_request_analytics", return_value=(
        {"total": 0, "open": 0, "funded": 0, "cancelled": 0, "expired": 0,
         "removed": 0, "duplicate": 0, "denied_by_mod": 0,
         "total_requested_usd": 0, "weekly": []}, None))
    def test_analytics_admin_ok(self, mock_anal):
        self._admin_session()
        r = self.client.get("/api/admin/request-analytics")
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertIn("total", d)

    @patch("services.expire_old_requests", return_value=(5, None))
    def test_expire_admin_ok(self, mock_exp):
        self._admin_session()
        r = self.client.post("/api/admin/requests/expire", json={"days": 10})
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertEqual(d["expired"], 5)

    @patch("services.expire_old_requests", return_value=(0, "DB error"))
    def test_expire_error_propagates(self, mock_exp):
        self._admin_session()
        r = self.client.post("/api/admin/requests/expire", json={})
        self.assertEqual(r.status_code, 500)

    # ── page routes ──────────────────────────────────────────────────────────

    def test_borrower_requests_page_requires_auth(self):
        r = self.client.get("/dashboard/borrower/requests")
        self.assertIn(r.status_code, (302, 401, 403))

    def test_borrower_requests_page_renders(self):
        self._session("alice", "borrower")
        r = self.client.get("/dashboard/borrower/requests")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Request History", r.data)

    def test_mod_request_queue_requires_mod(self):
        self._session("alice", "borrower")
        r = self.client.get("/dashboard/mod/requests")
        self.assertIn(r.status_code, (302, 401, 403))

    def test_mod_request_queue_mod_renders(self):
        self._mod_session()
        r = self.client.get("/dashboard/mod/requests")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Request Queue", r.data)

    def test_request_detail_page_requires_auth(self):
        r = self.client.get("/dashboard/requests/REQ-TESTPAGE1")
        self.assertIn(r.status_code, (302, 401, 403))

    @patch("services.get_loan_request", return_value=(
        {"id": 1, "request_id": "REQ-TESTPAGE1", "borrower_username": "alice",
         "reddit_username": None, "requested_amount": None,
         "requested_repayment_amount": None, "requested_due_date": None,
         "request_status": "open", "thread_url": None,
         "reddit_post_id": None, "reddit_comment_id": None,
         "created_at": "2026-06-01T00:00:00", "updated_at": "2026-06-01T00:00:00",
         "funded_loan_id": None, "notes": None, "funded_loan_ref": None}, None))
    def test_request_detail_page_renders(self, mock_get):
        self._session("alice", "borrower")
        r = self.client.get("/dashboard/requests/REQ-TESTPAGE1")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"REQ-TESTPAGE1", r.data)


if __name__ == "__main__":
    unittest.main()
