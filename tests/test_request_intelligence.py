"""Tests for Request Intelligence Sprint (Tasks 1-10)."""
import unittest
from unittest.mock import patch, MagicMock, call
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))


# ---------------------------------------------------------------------------
# flag_possible_duplicates
# ---------------------------------------------------------------------------

class FlagPossibleDuplicatesTests(unittest.TestCase):

    def _make_conn(self, rows=None):
        conn = MagicMock()
        cur  = MagicMock()
        cur.fetchall.return_value = rows or []
        conn.cursor.return_value  = cur
        return conn, cur

    @patch("services._get_db")
    @patch("services._ensure_loan_requests_table")
    @patch("services._ensure_request_events_table")
    @patch("services._notify_all_mods")
    def test_dry_run_returns_ids_no_commit(self, mock_notify, mock_evt, mock_tbl, mock_db):
        from services import flag_possible_duplicates
        conn, cur = self._make_conn([("REQ-AAA", "alice"), ("REQ-BBB", "alice")])
        mock_db.return_value = conn
        ids, err = flag_possible_duplicates(dry_run=True)
        self.assertIsNone(err)
        self.assertEqual(ids, ["REQ-AAA", "REQ-BBB"])
        conn.commit.assert_not_called()
        mock_notify.assert_not_called()

    @patch("services._get_db")
    @patch("services._ensure_loan_requests_table")
    @patch("services._ensure_request_events_table")
    @patch("services._notify_all_mods")
    def test_live_run_updates_and_commits(self, mock_notify, mock_evt, mock_tbl, mock_db):
        from services import flag_possible_duplicates
        conn, cur = self._make_conn([("REQ-AAA", "alice")])
        cur.rowcount = 1
        mock_db.return_value = conn
        ids, err = flag_possible_duplicates(dry_run=False)
        self.assertIsNone(err)
        self.assertIn("REQ-AAA", ids)
        conn.commit.assert_called()
        mock_notify.assert_called_once()

    @patch("services._get_db")
    @patch("services._ensure_loan_requests_table")
    @patch("services._ensure_request_events_table")
    @patch("services._notify_all_mods")
    def test_no_duplicates_returns_empty(self, mock_notify, mock_evt, mock_tbl, mock_db):
        from services import flag_possible_duplicates
        conn, cur = self._make_conn([])
        mock_db.return_value = conn
        ids, err = flag_possible_duplicates(dry_run=False)
        self.assertIsNone(err)
        self.assertEqual(ids, [])
        mock_notify.assert_not_called()

    @patch("services._get_db")
    def test_db_failure(self, mock_db):
        from services import flag_possible_duplicates
        mock_db.return_value = None
        ids, err = flag_possible_duplicates()
        self.assertEqual(ids, [])
        self.assertIn("Database", err)


# ---------------------------------------------------------------------------
# flag_missing_thread_links
# ---------------------------------------------------------------------------

class FlagMissingThreadLinksTests(unittest.TestCase):

    @patch("services._get_db")
    @patch("services._ensure_loan_requests_table")
    def test_returns_list(self, mock_tbl, mock_db):
        from services import flag_missing_thread_links
        conn = MagicMock(); cur = MagicMock()
        cur.fetchall.return_value = [
            ("REQ-001", "alice", 100.0, "open", datetime(2024, 1, 1)),
        ]
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        rows, err = flag_missing_thread_links()
        self.assertIsNone(err)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["request_id"], "REQ-001")

    @patch("services._get_db")
    @patch("services._ensure_loan_requests_table")
    def test_empty_returns_empty(self, mock_tbl, mock_db):
        from services import flag_missing_thread_links
        conn = MagicMock(); cur = MagicMock()
        cur.fetchall.return_value = []
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        rows, err = flag_missing_thread_links()
        self.assertIsNone(err)
        self.assertEqual(rows, [])

    @patch("services._get_db")
    def test_db_failure(self, mock_db):
        from services import flag_missing_thread_links
        mock_db.return_value = None
        rows, err = flag_missing_thread_links()
        self.assertEqual(rows, [])
        self.assertIn("Database", err)


# ---------------------------------------------------------------------------
# flag_unlinked_funded_requests
# ---------------------------------------------------------------------------

class FlagUnlinkedFundedRequestsTests(unittest.TestCase):

    @patch("services._get_db")
    @patch("services._ensure_loan_requests_table")
    def test_returns_funded_without_loan_id(self, mock_tbl, mock_db):
        from services import flag_unlinked_funded_requests
        conn = MagicMock(); cur = MagicMock()
        cur.fetchall.return_value = [
            ("REQ-002", "bob", 200.0, "funded", None, datetime(2024, 2, 1)),
        ]
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        rows, err = flag_unlinked_funded_requests()
        self.assertIsNone(err)
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["funded_loan_id"])

    @patch("services._get_db")
    def test_db_failure(self, mock_db):
        from services import flag_unlinked_funded_requests
        mock_db.return_value = None
        rows, err = flag_unlinked_funded_requests()
        self.assertEqual(rows, [])
        self.assertIn("Database", err)


# ---------------------------------------------------------------------------
# generate_request_quality_report
# ---------------------------------------------------------------------------

class GenerateRequestQualityReportTests(unittest.TestCase):

    def _mock_conn(self, side_effects):
        conn = MagicMock()
        cur  = MagicMock()
        cur.fetchone.side_effect  = [(v,) for v in side_effects]
        cur.fetchall.return_value = [("open", 5), ("funded", 3)]
        conn.cursor.return_value  = cur
        return conn

    @patch("services._get_db")
    @patch("services._ensure_loan_requests_table")
    def test_returns_report_dict(self, mock_tbl, mock_db):
        from services import generate_request_quality_report
        mock_db.return_value = self._mock_conn([0, 1, 2, 0, 0, 0])
        report, err = generate_request_quality_report()
        self.assertIsNone(err)
        self.assertIn("missing_borrower_username", report)
        self.assertIn("open_missing_thread_url", report)
        self.assertIn("missing_amount", report)
        self.assertIn("open_older_than_10_days", report)
        self.assertIn("funded_not_linked", report)
        self.assertIn("linked_to_missing_loan", report)
        self.assertIn("status_breakdown", report)
        self.assertIn("total_requests", report)

    @patch("services._get_db")
    @patch("services._ensure_loan_requests_table")
    def test_counts_are_correct(self, mock_tbl, mock_db):
        from services import generate_request_quality_report
        mock_db.return_value = self._mock_conn([0, 2, 3, 1, 1, 0])
        report, err = generate_request_quality_report()
        self.assertIsNone(err)
        self.assertEqual(report["open_missing_thread_url"], 2)
        self.assertEqual(report["missing_amount"], 3)

    @patch("services._get_db")
    def test_db_failure(self, mock_db):
        from services import generate_request_quality_report
        mock_db.return_value = None
        report, err = generate_request_quality_report()
        self.assertIsNone(report)
        self.assertIn("Database", err)


# ---------------------------------------------------------------------------
# backfill_requests_from_loans
# ---------------------------------------------------------------------------

class BackfillRequestsFromLoansTests(unittest.TestCase):

    @patch("services._get_db")
    @patch("services._ensure_loan_requests_table")
    @patch("services._ensure_request_events_table")
    @patch("services.log_event")
    def test_dry_run_counts_without_commit(self, mock_log, mock_evt, mock_tbl, mock_db):
        from services import backfill_requests_from_loans
        conn = MagicMock(); cur = MagicMock()
        cur.fetchall.return_value = [
            (1, "alice", "lender1", 100, datetime(2024, 1, 1), "https://reddit.com/r/borrow/1"),
            (2, "bob",   "lender2", 200, datetime(2024, 2, 1), None),
        ]
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        created, skipped, err = backfill_requests_from_loans(dry_run=True)
        self.assertIsNone(err)
        self.assertEqual(created, 2)
        self.assertEqual(skipped, 0)
        conn.commit.assert_not_called()

    @patch("services._get_db")
    @patch("services._ensure_loan_requests_table")
    @patch("services._ensure_request_events_table")
    @patch("services.log_event")
    @patch("services._generate_request_id", return_value="REQ-BACKFILL")
    def test_live_run_inserts_records(self, mock_gen, mock_log, mock_evt, mock_tbl, mock_db):
        from services import backfill_requests_from_loans
        conn = MagicMock(); cur = MagicMock()
        cur.fetchall.side_effect = [
            [(1, "alice", "lender1", 100, datetime(2024, 1, 1), "https://thread.url")],
            [],  # uniqueness check
        ]
        cur.fetchone.return_value = None
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        created, skipped, err = backfill_requests_from_loans(dry_run=False)
        self.assertIsNone(err)
        conn.commit.assert_called()

    @patch("services._get_db")
    @patch("services._ensure_loan_requests_table")
    @patch("services._ensure_request_events_table")
    @patch("services.log_event")
    def test_skips_loans_with_no_borrower(self, mock_log, mock_evt, mock_tbl, mock_db):
        from services import backfill_requests_from_loans
        conn = MagicMock(); cur = MagicMock()
        cur.fetchall.return_value = [(1, "", "lender1", 100, datetime(2024, 1, 1), None)]
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        created, skipped, err = backfill_requests_from_loans(dry_run=False)
        self.assertIsNone(err)
        self.assertEqual(created, 0)
        self.assertEqual(skipped, 1)

    @patch("services._get_db")
    def test_db_failure(self, mock_db):
        from services import backfill_requests_from_loans
        mock_db.return_value = None
        created, skipped, err = backfill_requests_from_loans()
        self.assertEqual(created, 0)
        self.assertIn("Database", err)


# ---------------------------------------------------------------------------
# get_request_analytics — expanded fields
# ---------------------------------------------------------------------------

class GetRequestAnalyticsExpandedTests(unittest.TestCase):

    @patch("services._get_db")
    @patch("services._ensure_loan_requests_table")
    def test_returns_expanded_fields(self, mock_tbl, mock_db):
        from services import get_request_analytics
        conn = MagicMock(); cur = MagicMock()
        # Return values for the main aggregate query (13 columns now)
        cur.fetchone.return_value = (
            20, 5, 10, 3, 2,  # total, open, funded, unfunded_active, closed_unfunded
            150.0, 200.0, 50.0,  # avg_requested, avg_funded_amount, funding_rate_pct
            4, 12, 2, 1, 3.5,   # this_week, this_month, expired_count, duplicate_flags, avg_days_to_funded
        )
        cur.fetchall.return_value = []
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        stats, err = get_request_analytics()
        self.assertIsNone(err)
        self.assertIn("this_week", stats)
        self.assertIn("this_month", stats)
        self.assertIn("expired_count", stats)
        self.assertIn("duplicate_flags", stats)
        self.assertIn("avg_days_to_funded", stats)
        self.assertEqual(stats["this_week"], 4.0)
        self.assertEqual(stats["expired_count"], 2.0)


# ---------------------------------------------------------------------------
# funded_backfill status acceptance
# ---------------------------------------------------------------------------

class FundedBackfillStatusTests(unittest.TestCase):

    @patch("services._get_db")
    @patch("services._ensure_loan_requests_table")
    @patch("services.log_event")
    def test_funded_backfill_is_valid_status(self, mock_log, mock_tbl, mock_db):
        from services import update_request_status
        conn = MagicMock(); cur = MagicMock()
        cur.fetchone.return_value = (1,)  # simulate row found by RETURNING id
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        ok, err = update_request_status("REQ-001", "funded_backfill", "system")
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_funded_backfill_in_lr_statuses(self):
        from services import _LR_STATUSES
        self.assertIn("funded_backfill", _LR_STATUSES)


# ---------------------------------------------------------------------------
# Permissions — new admin API routes
# ---------------------------------------------------------------------------

class AdminAutomationPermissionTests(unittest.TestCase):

    def setUp(self):
        import app as flask_app
        flask_app.app.config["TESTING"] = True
        flask_app.app.config["SECRET_KEY"] = "test-secret"
        self.client = flask_app.app.test_client()

    def _set_session(self, role):
        with self.client.session_transaction() as sess:
            sess["username"] = "testuser"
            sess["role"]     = role

    def test_flag_duplicates_requires_admin(self):
        self._set_session("mod")
        res = self.client.post("/api/admin/requests/flag-duplicates",
                               json={}, content_type="application/json")
        self.assertEqual(res.status_code, 403)

    def test_missing_threads_requires_admin(self):
        self._set_session("borrower")
        res = self.client.get("/api/admin/requests/missing-threads")
        self.assertEqual(res.status_code, 403)

    def test_unlinked_funded_requires_admin(self):
        self._set_session("lender")
        res = self.client.get("/api/admin/requests/unlinked-funded")
        self.assertEqual(res.status_code, 403)

    def test_quality_report_requires_admin(self):
        self._set_session("mod")
        res = self.client.get("/api/admin/requests/quality-report")
        self.assertEqual(res.status_code, 403)

    def test_backfill_requires_admin(self):
        self._set_session("mod")
        res = self.client.post("/api/admin/requests/backfill",
                               json={}, content_type="application/json")
        self.assertEqual(res.status_code, 403)

    def test_request_review_page_requires_mod(self):
        self._set_session("borrower")
        res = self.client.get("/dashboard/mod/request-review")
        self.assertIn(res.status_code, (302, 403))

    @patch("services.flag_possible_duplicates", return_value=(["REQ-AAA"], None))
    @patch("services.log_audit")
    def test_admin_can_flag_duplicates(self, mock_audit, mock_flag):
        self._set_session("admin")
        res = self.client.post("/api/admin/requests/flag-duplicates",
                               json={"dry_run": True}, content_type="application/json")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("flagged", data)

    @patch("services.flag_missing_thread_links", return_value=([], None))
    def test_admin_can_get_missing_threads(self, mock_fn):
        self._set_session("admin")
        res = self.client.get("/api/admin/requests/missing-threads")
        self.assertEqual(res.status_code, 200)

    @patch("services.flag_unlinked_funded_requests", return_value=([], None))
    def test_admin_can_get_unlinked_funded(self, mock_fn):
        self._set_session("admin")
        res = self.client.get("/api/admin/requests/unlinked-funded")
        self.assertEqual(res.status_code, 200)

    @patch("services.generate_request_quality_report", return_value=({"total_requests": 0}, None))
    def test_admin_can_get_quality_report(self, mock_fn):
        self._set_session("admin")
        res = self.client.get("/api/admin/requests/quality-report")
        self.assertEqual(res.status_code, 200)

    @patch("services.backfill_requests_from_loans", return_value=(0, 0, None))
    @patch("services.log_audit")
    def test_admin_can_backfill(self, mock_audit, mock_fn):
        self._set_session("admin")
        res = self.client.post("/api/admin/requests/backfill",
                               json={"dry_run": True}, content_type="application/json")
        self.assertEqual(res.status_code, 200)

    @patch("services.flag_possible_duplicates", return_value=(None, "DB error"))
    def test_flag_duplicates_error_returns_500(self, mock_fn):
        self._set_session("admin")
        res = self.client.post("/api/admin/requests/flag-duplicates",
                               json={}, content_type="application/json")
        self.assertEqual(res.status_code, 500)


# ---------------------------------------------------------------------------
# Notifications wired to request events
# ---------------------------------------------------------------------------

class RequestNotificationTests(unittest.TestCase):

    def setUp(self):
        import app as flask_app
        flask_app.app.config["TESTING"] = True
        flask_app.app.config["SECRET_KEY"] = "test-secret"
        self.client = flask_app.app.test_client()
        with self.client.session_transaction() as sess:
            sess["username"] = "alice"
            sess["role"]     = "borrower"

    @patch("services.create_loan_request", return_value=("REQ-NOTIF01", None))
    @patch("services.log_request_event", return_value=(1, None))
    @patch("services.find_duplicate_loan_requests", return_value=([], None))
    @patch("services.create_notification")
    def test_create_request_notifies_borrower(self, mock_notif, mock_dupes, mock_event, mock_create):
        res = self.client.post("/api/loan-requests",
                               json={"borrower_username": "alice"},
                               content_type="application/json")
        self.assertEqual(res.status_code, 201)
        mock_notif.assert_called()
        call_args = mock_notif.call_args[0]
        self.assertEqual(call_args[0], "alice")
        self.assertEqual(call_args[1], "request_recorded")

    @patch("services.create_loan_request", return_value=("REQ-NOTIF02", None))
    @patch("services.log_request_event", return_value=(1, None))
    @patch("services.find_duplicate_loan_requests", return_value=(["REQ-OLD"], None))
    @patch("services.create_notification")
    @patch("services._notify_all_mods")
    def test_duplicate_detected_notifies_mods(self, mock_mods, mock_notif, mock_dupes, mock_event, mock_create):
        res = self.client.post("/api/loan-requests",
                               json={"borrower_username": "alice"},
                               content_type="application/json")
        self.assertEqual(res.status_code, 201)
        mock_mods.assert_called_once()

    @patch("services.update_request_status", return_value=(True, None))
    @patch("services.log_audit")
    @patch("services.log_request_event", return_value=(1, None))
    @patch("services.get_loan_request", return_value=({"borrower_username": "alice"}, None))
    @patch("services.create_notification")
    def test_funded_status_notifies_borrower(self, mock_notif, mock_get, mock_event, mock_audit, mock_update):
        with self.client.session_transaction() as sess:
            sess["username"] = "mod1"
            sess["role"]     = "mod"
        res = self.client.patch("/api/loan-requests/REQ-001/status",
                                json={"status": "funded"},
                                content_type="application/json")
        self.assertEqual(res.status_code, 200)
        notif_calls = [c[0] for c in mock_notif.call_args_list]
        types = [c[1] for c in notif_calls]
        self.assertIn("request_funded", types)

    @patch("services.update_request_status", return_value=(True, None))
    @patch("services.log_audit")
    @patch("services.log_request_event", return_value=(1, None))
    @patch("services.get_loan_request", return_value=({"borrower_username": "alice"}, None))
    @patch("services.create_notification")
    def test_expired_status_notifies_borrower(self, mock_notif, mock_get, mock_event, mock_audit, mock_update):
        with self.client.session_transaction() as sess:
            sess["username"] = "mod1"
            sess["role"]     = "mod"
        res = self.client.patch("/api/loan-requests/REQ-001/status",
                                json={"status": "expired"},
                                content_type="application/json")
        self.assertEqual(res.status_code, 200)
        notif_calls = [c[0] for c in mock_notif.call_args_list]
        types = [c[1] for c in notif_calls]
        self.assertIn("request_expired", types)


# ---------------------------------------------------------------------------
# Review dashboard page
# ---------------------------------------------------------------------------

class RequestReviewDashboardTests(unittest.TestCase):

    def setUp(self):
        import app as flask_app
        flask_app.app.config["TESTING"] = True
        flask_app.app.config["SECRET_KEY"] = "test-secret"
        self.client = flask_app.app.test_client()

    def _set_session(self, role):
        with self.client.session_transaction() as sess:
            sess["username"] = "reviewer"
            sess["role"]     = role

    def test_mod_can_access_review_page(self):
        self._set_session("mod")
        res = self.client.get("/dashboard/mod/request-review")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Request Review", res.data)

    def test_admin_can_access_review_page(self):
        self._set_session("admin")
        res = self.client.get("/dashboard/mod/request-review")
        self.assertEqual(res.status_code, 200)

    def test_borrower_blocked_from_review_page(self):
        self._set_session("borrower")
        res = self.client.get("/dashboard/mod/request-review")
        self.assertIn(res.status_code, (302, 403))

    def test_lender_blocked_from_review_page(self):
        self._set_session("lender")
        res = self.client.get("/dashboard/mod/request-review")
        self.assertIn(res.status_code, (302, 403))


# ---------------------------------------------------------------------------
# Audit log integration — status changes
# ---------------------------------------------------------------------------

class AuditLogIntegrationTests(unittest.TestCase):

    def setUp(self):
        import app as flask_app
        flask_app.app.config["TESTING"] = True
        flask_app.app.config["SECRET_KEY"] = "test-secret"
        self.client = flask_app.app.test_client()
        with self.client.session_transaction() as sess:
            sess["username"] = "moduser"
            sess["role"]     = "mod"

    @patch("services.update_request_status", return_value=(True, None))
    @patch("services.log_audit")
    @patch("services.log_request_event", return_value=(1, None))
    @patch("services.get_loan_request", return_value=({"borrower_username": "alice"}, None))
    @patch("services.create_notification")
    def test_status_change_calls_log_audit(self, mock_notif, mock_get, mock_event, mock_audit, mock_update):
        res = self.client.patch("/api/loan-requests/REQ-001/status",
                                json={"status": "removed", "note": "test"},
                                content_type="application/json")
        self.assertEqual(res.status_code, 200)
        mock_audit.assert_called_once()
        audit_kwargs = mock_audit.call_args
        self.assertIn("request_status_updated", audit_kwargs[0])

    @patch("services.update_request_status", return_value=(True, None))
    @patch("services.log_audit")
    @patch("services.log_request_event", return_value=(1, None))
    @patch("services.get_loan_request", return_value=({"borrower_username": "alice"}, None))
    @patch("services.create_notification")
    def test_status_change_logs_request_event(self, mock_notif, mock_get, mock_event, mock_audit, mock_update):
        res = self.client.patch("/api/loan-requests/REQ-002/status",
                                json={"status": "duplicate"},
                                content_type="application/json")
        self.assertEqual(res.status_code, 200)
        mock_event.assert_called()
        event_type = mock_event.call_args[0][1]
        self.assertEqual(event_type, "status_changed")

    @patch("services.link_request_to_loan", return_value=(True, None))
    @patch("services.log_audit")
    @patch("services.log_request_event", return_value=(1, None))
    def test_link_action_calls_log_audit(self, mock_event, mock_audit, mock_link):
        res = self.client.post("/api/loan-requests/REQ-003/link",
                               json={"loan_db_id": 42},
                               content_type="application/json")
        self.assertEqual(res.status_code, 200)
        mock_audit.assert_called_once()

    @patch("services.link_request_to_loan", return_value=(True, None))
    @patch("services.log_audit")
    @patch("services.log_request_event", return_value=(1, None))
    def test_link_action_logs_request_event(self, mock_event, mock_audit, mock_link):
        res = self.client.post("/api/loan-requests/REQ-003/link",
                               json={"loan_db_id": 42},
                               content_type="application/json")
        self.assertEqual(res.status_code, 200)
        mock_event.assert_called()
        event_type = mock_event.call_args[0][1]
        self.assertEqual(event_type, "linked_to_loan")


# ---------------------------------------------------------------------------
# _notify_all_mods
# ---------------------------------------------------------------------------

class NotifyAllModsTests(unittest.TestCase):

    @patch("services._get_db")
    @patch("services.create_notification")
    def test_notifies_each_mod(self, mock_notif, mock_db):
        from services import _notify_all_mods
        conn = MagicMock(); cur = MagicMock()
        cur.fetchall.return_value = [("mod1",), ("mod2",), ("admin1",)]
        conn.cursor.return_value  = cur
        mock_db.return_value = conn
        _notify_all_mods("test_type", "Test Title", "Test message.")
        self.assertEqual(mock_notif.call_count, 3)

    @patch("services._get_db")
    @patch("services.create_notification")
    def test_no_mods_no_notifications(self, mock_notif, mock_db):
        from services import _notify_all_mods
        conn = MagicMock(); cur = MagicMock()
        cur.fetchall.return_value = []
        conn.cursor.return_value  = cur
        mock_db.return_value = conn
        _notify_all_mods("test_type", "Title", "Message.")
        mock_notif.assert_not_called()

    @patch("services._get_db")
    def test_db_failure_is_silent(self, mock_db):
        from services import _notify_all_mods
        mock_db.return_value = None
        # Should not raise
        _notify_all_mods("test_type", "Title", "Message.")


if __name__ == "__main__":
    unittest.main()
