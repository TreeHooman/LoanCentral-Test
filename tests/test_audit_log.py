"""Tests for audit logging, loan events, notifications, verified lender, global search."""
import sys
import unittest
from unittest.mock import patch, MagicMock


def _make_conn(rows=None, count=0):
    """Build a fake psycopg2 connection/cursor."""
    cur = MagicMock()
    cur.fetchone.return_value = (count,)
    cur.fetchall.return_value = rows or []
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn, cur


class AuditLogTests(unittest.TestCase):

    def test_log_audit_inserts_row(self):
        conn, cur = _make_conn()
        with patch("services._get_db", return_value=conn):
            from services import log_audit
            result = log_audit("mod1", "mod", "loan_created",
                               target_type="loan", target_id="42",
                               new_value={"amount": 100})
        self.assertTrue(result)
        cur.execute.assert_called()
        conn.commit.assert_called()

    def test_log_audit_no_db_returns_false(self):
        with patch("services._get_db", return_value=None):
            from services import log_audit
            result = log_audit("mod1", "mod", "loan_created")
        self.assertFalse(result)

    def test_get_audit_log_returns_rows(self):
        import json
        from datetime import datetime
        fake_row = (1, "mod1", "mod", "loan_created", "loan", "42",
                    None, json.dumps({"amount": 100}), None, None,
                    datetime(2026, 1, 1))
        conn, cur = _make_conn(rows=[fake_row], count=1)
        cur.fetchone.side_effect = [(1,), fake_row]
        cur.fetchall.return_value = [fake_row]
        with patch("services._get_db", return_value=conn):
            from services import get_audit_log
            rows, total, err = get_audit_log(action_type="loan_created")
        self.assertIsNone(err)
        self.assertEqual(total, 1)

    def test_get_audit_log_filters_username(self):
        conn, cur = _make_conn(rows=[], count=0)
        with patch("services._get_db", return_value=conn):
            from services import get_audit_log
            rows, total, err = get_audit_log(username="specificuser")
        self.assertIsNone(err)
        # Verify WHERE clause was used — username param passed to execute
        call_args = str(cur.execute.call_args_list)
        self.assertIn("specificuser", call_args)


class LoanEventTests(unittest.TestCase):

    def test_add_loan_event_inserts(self):
        conn, cur = _make_conn()
        with patch("services._get_db", return_value=conn):
            from services import add_loan_event
            result = add_loan_event("42", "loan_created", "lender1", "Initial loan")
        self.assertTrue(result)
        cur.execute.assert_called()
        conn.commit.assert_called()

    def test_add_loan_event_no_db_returns_false(self):
        with patch("services._get_db", return_value=None):
            from services import add_loan_event
            result = add_loan_event("42", "loan_created")
        self.assertFalse(result)

    def test_get_loan_events_returns_ordered(self):
        from datetime import datetime
        fake_rows = [
            (2, "42", "loan_repaid", "lender1", "Paid", datetime(2026, 6, 2)),
            (1, "42", "loan_created", "lender1", "Created", datetime(2026, 6, 1)),
        ]
        conn, cur = _make_conn(rows=fake_rows)
        with patch("services._get_db", return_value=conn):
            from services import get_loan_events
            events, err = get_loan_events("42")
        self.assertIsNone(err)
        self.assertEqual(len(events), 2)
        # Newest first
        self.assertEqual(events[0]["event_type"], "loan_repaid")


class NotificationTests(unittest.TestCase):

    def test_create_notification(self):
        conn, cur = _make_conn()
        with patch("services._get_db", return_value=conn):
            from services import create_notification
            result = create_notification("borrower1", "due_soon",
                                         "Payment Due Soon", "Your loan is due in 3 days.")
        self.assertTrue(result)
        conn.commit.assert_called()

    def test_get_notifications_returns_unread_count(self):
        from datetime import datetime
        fake_notif = (1, "borrower1", "due_soon", "Due soon", "msg", False, datetime(2026, 1, 1))
        conn, cur = _make_conn(rows=[fake_notif], count=1)
        cur.fetchone.side_effect = [(1,), (1,)]
        cur.fetchall.return_value = [fake_notif]
        with patch("services._get_db", return_value=conn):
            from services import get_notifications
            notifs, unread, total, err = get_notifications("borrower1")
        self.assertIsNone(err)
        self.assertEqual(unread, 1)

    def test_mark_notifications_read_all(self):
        conn, cur = _make_conn()
        with patch("services._get_db", return_value=conn):
            from services import mark_notifications_read
            ok, err = mark_notifications_read("borrower1")
        self.assertTrue(ok)
        self.assertIsNone(err)
        conn.commit.assert_called()

    def test_mark_notifications_read_specific(self):
        conn, cur = _make_conn()
        with patch("services._get_db", return_value=conn):
            from services import mark_notifications_read
            ok, err = mark_notifications_read("borrower1", [1, 2, 3])
        self.assertTrue(ok)
        self.assertIsNone(err)


class VerifiedLenderTests(unittest.TestCase):

    def test_set_verified_lender_grant(self):
        conn, cur = _make_conn()
        with patch("services._get_db", return_value=conn):
            from services import set_verified_lender
            ok, err = set_verified_lender("lender1", True, "mod1", "Completed verification")
        self.assertTrue(ok)
        self.assertIsNone(err)
        conn.commit.assert_called()

    def test_set_verified_lender_revoke(self):
        conn, cur = _make_conn()
        with patch("services._get_db", return_value=conn):
            from services import set_verified_lender
            ok, err = set_verified_lender("lender1", False, "mod1", "Revoked")
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_get_verified_lender_status_true(self):
        from datetime import datetime
        conn, cur = _make_conn()
        cur.fetchone.return_value = (True, datetime(2026,1,1), "mod1", "note", "lender")
        with patch("services._get_db", return_value=conn):
            from services import get_verified_lender_status
            verified, details, err = get_verified_lender_status("lender1")
        self.assertTrue(verified)
        self.assertEqual(details["verified_by"], "mod1")
        self.assertIsNone(err)

    def test_get_verified_lender_status_not_found(self):
        conn, cur = _make_conn()
        cur.fetchone.return_value = None
        with patch("services._get_db", return_value=conn):
            from services import get_verified_lender_status
            verified, details, err = get_verified_lender_status("nobody")
        self.assertFalse(verified)
        self.assertIsNone(err)


class GlobalSearchTests(unittest.TestCase):

    def test_search_loans(self):
        from datetime import datetime
        from decimal import Decimal
        fake_loan = ("L001", "lender1", "borrower1", Decimal("100"), "USD",
                     "confirmed", None, datetime(2026,1,1))
        conn, cur = _make_conn(rows=[fake_loan])
        with patch("services._get_db", return_value=conn):
            from services import global_search
            results, total, err = global_search("lender1", search_type="loans")
        self.assertIsNone(err)
        self.assertIn("loans", results)

    def test_search_users(self):
        from datetime import datetime
        fake_user = ("lender1", "lender", True, datetime(2026,1,1))
        conn, cur = _make_conn(rows=[fake_user])
        with patch("services._get_db", return_value=conn):
            from services import global_search
            results, total, err = global_search("lender1", search_type="users")
        self.assertIsNone(err)
        self.assertIn("users", results)

    def test_search_empty_query(self):
        conn, cur = _make_conn(rows=[])
        with patch("services._get_db", return_value=conn):
            from services import global_search
            results, total, err = global_search("", search_type="loans")
        self.assertIsNone(err)

    def test_search_no_db(self):
        with patch("services._get_db", return_value=None):
            from services import global_search
            results, total, err = global_search("test")
        self.assertIsNotNone(err)
        self.assertEqual(total, 0)


if __name__ == "__main__":
    unittest.main()
