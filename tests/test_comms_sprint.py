"""Tests for Communication Sprint: notification queue, templates, reminders."""
import unittest
from unittest.mock import patch, MagicMock, call
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

from services import (
    render_notification_body,
    get_notification_subject,
    _NOTIF_QUEUE_TYPES,
    _NOTIF_QUEUE_CHANNELS,
)


# ---------------------------------------------------------------------------
# render_notification_body / get_notification_subject
# ---------------------------------------------------------------------------

class RenderNotificationBodyTests(unittest.TestCase):

    def test_email_loan_reminder_7d_renders(self):
        ctx = {"username": "alice", "loan_id": "LC-001",
                "amount": "100.00", "currency": "USD", "due_date": "2026-06-17",
                "lender": "bob"}
        body = render_notification_body("loan_reminder_7d", "email", ctx)
        self.assertIn("alice", body)
        self.assertIn("LC-001", body)
        self.assertIn("7 days", body)
        self.assertIn("LoanCentral", body)

    def test_sms_loan_reminder_1d_renders(self):
        ctx = {"username": "alice", "loan_id": "LC-002",
                "amount": "50.00", "currency": "USD", "due_date": "2026-06-11"}
        body = render_notification_body("loan_reminder_1d", "sms", ctx)
        self.assertIn("LC-002", body)
        self.assertIn("tomorrow", body)

    def test_missing_context_keys_do_not_crash(self):
        body = render_notification_body("loan_reminder_7d", "email", {})
        self.assertIsInstance(body, str)

    def test_verification_approved_email(self):
        body = render_notification_body("verification_approved", "email",
                                        {"username": "carol"})
        self.assertIn("carol", body)
        self.assertIn("approved", body)

    def test_verification_denied_email(self):
        body = render_notification_body("verification_denied", "email",
                                        {"username": "dave"})
        self.assertIn("Denied", body)

    def test_dispute_opened_email(self):
        body = render_notification_body("dispute_opened", "email",
                                        {"username": "eve", "loan_id": "LC-003"})
        self.assertIn("dispute", body.lower())
        self.assertIn("LC-003", body)

    def test_account_notification_email(self):
        body = render_notification_body("account_notification", "email",
                                        {"username": "frank", "message": "Hello!"})
        self.assertIn("Hello!", body)

    def test_sms_verification_approved(self):
        body = render_notification_body("verification_approved", "sms", {})
        self.assertIn("approved", body.lower())

    def test_unknown_type_falls_back_gracefully(self):
        body = render_notification_body("nonexistent_type", "email", {"username": "x"})
        self.assertIsInstance(body, str)

    def test_get_notification_subject_known(self):
        s = get_notification_subject("loan_reminder_7d")
        self.assertIn("7 days", s)

    def test_get_notification_subject_unknown(self):
        s = get_notification_subject("unknown_type")
        self.assertIsInstance(s, str)
        self.assertTrue(len(s) > 0)

    def test_informational_language_no_threats(self):
        for nt in ("loan_reminder_7d", "loan_reminder_3d", "loan_reminder_1d", "loan_reminder_due"):
            body = render_notification_body(nt, "email",
                {"username": "u", "loan_id": "L1", "amount": "10", "currency": "USD", "due_date": "2026-06-10"})
            for bad in ("demand", "collections", "legal action", "attorney", "harass"):
                self.assertNotIn(bad, body.lower(), f"{nt} body contains '{bad}'")

    def test_all_reminder_types_covered_in_sms(self):
        for nt in ("loan_reminder_7d", "loan_reminder_3d", "loan_reminder_1d", "loan_reminder_due"):
            body = render_notification_body(nt, "sms",
                {"loan_id": "L", "amount": "5", "currency": "USD", "due_date": "2026-06-10"})
            self.assertIn("LoanCentral", body)


# ---------------------------------------------------------------------------
# queue_notification — unit tests with mocked DB
# ---------------------------------------------------------------------------

class QueueNotificationTests(unittest.TestCase):

    def _make_conn(self, queue_id=42):
        conn = MagicMock()
        cur  = MagicMock()
        cur.fetchone.return_value = (queue_id,)
        conn.cursor.return_value  = cur
        return conn, cur

    @patch("services._get_db")
    @patch("services.log_event")
    def test_queue_email_notification(self, mock_log, mock_db):
        from services import queue_notification
        conn, cur = self._make_conn(99)
        mock_db.return_value = conn
        qid, err = queue_notification("alice", "loan_reminder_7d", "email",
                                       {"username": "alice", "loan_id": "L1",
                                        "amount": "10.00", "currency": "USD",
                                        "due_date": "2026-06-17"})
        self.assertIsNone(err)
        self.assertEqual(qid, 99)
        conn.commit.assert_called()
        mock_log.assert_called_once()

    @patch("services._get_db")
    def test_queue_invalid_channel_returns_error(self, mock_db):
        from services import queue_notification
        qid, err = queue_notification("alice", "loan_reminder_7d", "fax")
        self.assertIsNone(qid)
        self.assertIn("Invalid channel", err)
        mock_db.assert_not_called()

    @patch("services._get_db")
    def test_queue_invalid_type_returns_error(self, mock_db):
        from services import queue_notification
        qid, err = queue_notification("alice", "made_up_type", "email")
        self.assertIsNone(qid)
        self.assertIn("Unknown notification type", err)
        mock_db.assert_not_called()

    @patch("services._get_db")
    def test_queue_db_failure_returns_error(self, mock_db):
        from services import queue_notification
        mock_db.return_value = None
        qid, err = queue_notification("alice", "loan_reminder_7d", "email")
        self.assertIsNone(qid)
        self.assertIn("Database", err)

    @patch("services._get_db")
    @patch("services.log_event")
    def test_queue_sms_notification(self, mock_log, mock_db):
        from services import queue_notification
        conn, cur = self._make_conn(7)
        mock_db.return_value = conn
        qid, err = queue_notification("bob", "loan_reminder_due", "sms",
                                       {"loan_id": "L2", "amount": "20.00",
                                        "currency": "USD", "due_date": "2026-06-10"})
        self.assertIsNone(err)
        self.assertEqual(qid, 7)


# ---------------------------------------------------------------------------
# get_notification_queue
# ---------------------------------------------------------------------------

class GetNotificationQueueTests(unittest.TestCase):

    def _make_conn(self, rows=None):
        conn = MagicMock()
        cur  = MagicMock()
        fetch_seq = [[(0,)]]  # ensure table call
        if rows is not None:
            cur.fetchone.side_effect = [(len(rows),)]
            cur.fetchall.return_value = rows
        conn.cursor.return_value = cur
        return conn, cur

    @patch("services._get_db")
    def test_returns_rows_and_total(self, mock_db):
        from services import get_notification_queue
        from datetime import datetime
        conn = MagicMock()
        cur  = MagicMock()
        cur.fetchone.return_value = (2,)
        cur.fetchall.return_value = [
            (1, "alice", "email", "loan_reminder_7d", "Subject", "pending",
             0, datetime(2026,6,10), None, None),
        ]
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        rows, total, err = get_notification_queue()
        self.assertIsNone(err)
        self.assertEqual(total, 2)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["recipient"], "alice")

    @patch("services._get_db")
    def test_db_failure_returns_error(self, mock_db):
        from services import get_notification_queue
        mock_db.return_value = None
        rows, total, err = get_notification_queue()
        self.assertEqual(rows, [])
        self.assertEqual(total, 0)
        self.assertIn("Database", err)


# ---------------------------------------------------------------------------
# mark_notification_sent / mark_notification_failed
# ---------------------------------------------------------------------------

class MarkNotificationTests(unittest.TestCase):

    @patch("services._get_db")
    def test_mark_sent_ok(self, mock_db):
        from services import mark_notification_sent
        conn = MagicMock(); conn.cursor.return_value = MagicMock()
        mock_db.return_value = conn
        ok, err = mark_notification_sent(1)
        self.assertTrue(ok)
        self.assertIsNone(err)

    @patch("services._get_db")
    def test_mark_failed_ok(self, mock_db):
        from services import mark_notification_failed
        conn = MagicMock(); conn.cursor.return_value = MagicMock()
        mock_db.return_value = conn
        ok, err = mark_notification_failed(1, "SMTP timeout")
        self.assertTrue(ok)
        self.assertIsNone(err)

    @patch("services._get_db")
    def test_mark_sent_db_failure(self, mock_db):
        from services import mark_notification_sent
        mock_db.return_value = None
        ok, err = mark_notification_sent(1)
        self.assertFalse(ok)
        self.assertIn("Database", err)

    @patch("services._get_db")
    def test_mark_failed_db_failure(self, mock_db):
        from services import mark_notification_failed
        mock_db.return_value = None
        ok, err = mark_notification_failed(1, "err")
        self.assertFalse(ok)


# ---------------------------------------------------------------------------
# get_queue_stats
# ---------------------------------------------------------------------------

class GetQueueStatsTests(unittest.TestCase):

    @patch("services._get_db")
    def test_returns_stats_dict(self, mock_db):
        from services import get_queue_stats
        conn = MagicMock(); cur = MagicMock()
        cur.fetchone.return_value = (3, 10, 1, 0, 12, 2, 14)
        conn.cursor.return_value = cur
        mock_db.return_value = conn
        stats, err = get_queue_stats()
        self.assertIsNone(err)
        self.assertEqual(stats["pending"],     3)
        self.assertEqual(stats["sent"],        10)
        self.assertEqual(stats["failed"],      1)
        self.assertEqual(stats["email_total"], 12)
        self.assertEqual(stats["total"],       14)

    @patch("services._get_db")
    def test_db_failure_returns_error(self, mock_db):
        from services import get_queue_stats
        mock_db.return_value = None
        stats, err = get_queue_stats()
        self.assertIsNone(stats)
        self.assertIn("Database", err)


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

class CommsAPITests(unittest.TestCase):

    def setUp(self):
        import app as flask_app
        flask_app.app.config["TESTING"] = True
        flask_app.app.config["SECRET_KEY"] = "test"
        self.client = flask_app.app.test_client()

    def _admin_session(self):
        with self.client.session_transaction() as s:
            s["username"] = "testadmin"
            s["role"]     = "admin"
            s["perm_version"] = 0

    def test_queue_stats_requires_auth(self):
        r = self.client.get("/api/admin/notifications/queue/stats")
        self.assertIn(r.status_code, (401, 403))

    def test_queue_list_requires_auth(self):
        r = self.client.get("/api/admin/notifications/queue")
        self.assertIn(r.status_code, (401, 403))

    def test_trigger_reminders_requires_auth(self):
        r = self.client.post("/api/admin/notifications/queue/reminders",
                              json={})
        self.assertIn(r.status_code, (401, 403))

    @patch("services.get_queue_stats", return_value=({"pending": 0, "sent": 0, "failed": 0, "retried": 0, "email_total": 0, "sms_total": 0, "total": 0}, None))
    def test_queue_stats_admin_ok(self, mock_stats):
        self._admin_session()
        r = self.client.get("/api/admin/notifications/queue/stats")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("total", data)

    @patch("services.get_notification_queue", return_value=([], 0, None))
    def test_queue_list_admin_ok(self, mock_q):
        self._admin_session()
        r = self.client.get("/api/admin/notifications/queue")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("queue", data)

    @patch("services.queue_due_reminders", return_value=(5, 3, None))
    def test_trigger_reminders_dry_run(self, mock_rem):
        self._admin_session()
        r = self.client.post("/api/admin/notifications/queue/reminders",
                              json={"dry_run": True})
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertEqual(d["queued"],  5)
        self.assertEqual(d["skipped"], 3)
        self.assertTrue(d["dry_run"])

    @patch("services.queue_due_reminders", return_value=(0, 0, "DB error"))
    def test_trigger_reminders_error_propagates(self, mock_rem):
        self._admin_session()
        r = self.client.post("/api/admin/notifications/queue/reminders",
                              json={})
        self.assertEqual(r.status_code, 500)

    def test_communications_page_requires_admin(self):
        r = self.client.get("/admin/communications")
        self.assertIn(r.status_code, (302, 401, 403))

    def test_communications_page_admin_renders(self):
        self._admin_session()
        r = self.client.get("/admin/communications")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Communications", r.data)


if __name__ == "__main__":
    unittest.main()
