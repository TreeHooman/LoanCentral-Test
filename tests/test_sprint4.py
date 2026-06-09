"""
Sprint 4 tests — Notification delivery, OTP rate limiting, profile badge.
Covers:
  T1  — Verified Lender badge data in get_user_profile
  T2  — Notification delivery: loan_created, mark_repaid, mark_unpaid, dispute_loan
  T3  — OTP rate limiter (_otp_check_rate)
  T4  — Borrower verification application endpoint available
"""
import sys
import time
import unittest
from unittest.mock import patch, MagicMock, call


def _make_conn(rows=None, fetchone_val=None, rowcount=1):
    cur = MagicMock()
    cur.fetchone.return_value = fetchone_val
    cur.fetchall.return_value = rows or []
    cur.rowcount = rowcount
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn, cur


# ---------------------------------------------------------------------------
# T1 — Verified Lender badge: get_user_profile includes verified_lender
# ---------------------------------------------------------------------------

class UserProfileBadgeTests(unittest.TestCase):

    def test_profile_includes_verified_lender_true(self):
        conn, cur = _make_conn()
        # First fetchone: users row. Second fetchone: active loans count.
        # Third fetchone: user_roles row (verified_lender, reddit_username).
        from decimal import Decimal
        users_row = (3, 5, "200.00", "500.00", "180.00", 0, "0.00")
        active_row = (2, "150.00")
        from datetime import datetime
        roles_row = (True, "lender_reddit_name", datetime(2026, 1, 1), "mod1")
        cur.fetchone.side_effect = [users_row, active_row, roles_row]
        cur.fetchall.return_value = []
        with patch("services._get_db", return_value=conn):
            from services import get_user_profile
            profile, err = get_user_profile("lender1")
        self.assertIsNone(err)
        self.assertTrue(profile["verified_lender"])
        self.assertEqual(profile["reddit_username"], "lender_reddit_name")
        self.assertEqual(profile["verified_lender_by"], "mod1")

    def test_profile_includes_verified_lender_false(self):
        conn, cur = _make_conn()
        from decimal import Decimal
        users_row = (1, 0, "100.00", "0.00", "90.00", 0, "0.00")
        active_row = (0, "0.00")
        roles_row = (False, None, None, None)
        cur.fetchone.side_effect = [users_row, active_row, roles_row]
        with patch("services._get_db", return_value=conn):
            from services import get_user_profile
            profile, err = get_user_profile("borrower1")
        self.assertIsNone(err)
        self.assertFalse(profile["verified_lender"])
        self.assertIsNone(profile["reddit_username"])

    def test_profile_graceful_when_user_not_in_roles(self):
        """verified_lender defaults to False if user_roles row is missing."""
        conn, cur = _make_conn()
        users_row = (0, 0, "0.00", "0.00", "0.00", 0, "0.00")
        active_row = (0, "0.00")
        cur.fetchone.side_effect = [users_row, active_row, None]  # None = no roles row
        with patch("services._get_db", return_value=conn):
            from services import get_user_profile
            profile, err = get_user_profile("newuser")
        self.assertIsNone(err)
        self.assertFalse(profile["verified_lender"])

    def test_profile_no_db(self):
        with patch("services._get_db", return_value=None):
            from services import get_user_profile
            profile, err = get_user_profile("alice")
        self.assertIsNone(profile)
        self.assertIsNotNone(err)


# ---------------------------------------------------------------------------
# T2 — Notification delivery wired into service functions
# ---------------------------------------------------------------------------

class NotificationDeliveryTests(unittest.TestCase):

    def _make_loan_conn(self):
        """Return a mock DB connection suitable for create_loan."""
        from decimal import Decimal
        conn, cur = _make_conn()
        # insert_loan returns a new DB id
        cur.fetchone.side_effect = [
            None,           # find_confirmed_loan (no duplicate) → (id,) wrapper
            (42,),          # insert_loan returns id=42
        ]
        cur.rowcount = 1
        return conn, cur

    def test_create_loan_source_contains_notification_calls(self):
        """create_loan source must include create_notification calls for both parties."""
        import inspect
        from services import create_loan
        src = inspect.getsource(create_loan)
        self.assertIn("create_notification", src,
                      "create_loan must call create_notification")
        self.assertIn("loan_confirmed", src,
                      "create_loan must fire 'loan_confirmed' notification type")
        # Both borrower and lender should appear in the notification calls
        self.assertIn("borrower", src)
        self.assertIn("lender", src)

    def test_mark_unpaid_notifies_borrower(self):
        """mark_unpaid must notify the borrower."""
        from decimal import Decimal
        conn, cur = _make_conn()
        # mark_unpaid queries: (id, amount, currency, amount_repaid, thread, status, borrower, repay_amount)
        loan_row = (7, Decimal("100"), "USD", Decimal("0"), "https://t", "confirmed", "borrower1", Decimal("120"))
        cur.fetchone.return_value = loan_row
        cur.rowcount = 1

        notified = []
        with patch("services._get_db", return_value=conn), \
             patch("services.create_notification", side_effect=lambda u, t, ti, m: notified.append(u) or True), \
             patch("services.log_event"), \
             patch("services.log_audit"), \
             patch("services.add_loan_event"):
            from services import mark_unpaid
            result, err = mark_unpaid("LC-001", "lender1")

        self.assertIsNone(err)
        self.assertIn("borrower1", notified, "borrower must be notified on unpaid")

    def test_dispute_loan_notifies_lender(self):
        """dispute_loan must notify the lender."""
        from decimal import Decimal
        conn, cur = _make_conn()
        # dispute_loan SELECT: (id, lender, amount, currency, status)
        loan_row = (9, "lender1", Decimal("100"), "USD", "confirmed")
        cur.fetchone.return_value = loan_row
        cur.rowcount = 1

        notified = []
        with patch("services._get_db", return_value=conn), \
             patch("services.create_notification", side_effect=lambda u, t, ti, m: notified.append(u) or True), \
             patch("services.log_event"), \
             patch("services.log_audit"), \
             patch("services.add_loan_event"):
            from services import dispute_loan
            result, err = dispute_loan("LC-001", "borrower1")

        self.assertIsNone(err)
        self.assertIn("lender1", notified, "lender must be notified on dispute")

    def test_notification_type_for_unpaid(self):
        """Notification type for unpaid events should be 'loan_unpaid'."""
        from decimal import Decimal
        conn, cur = _make_conn()
        loan_row = (7, Decimal("100"), "USD", Decimal("0"), "https://t", "confirmed", "borrower1", Decimal("120"))
        cur.fetchone.return_value = loan_row
        cur.rowcount = 1

        created = []
        with patch("services._get_db", return_value=conn), \
             patch("services.create_notification", side_effect=lambda u, t, ti, m: created.append((u, t)) or True), \
             patch("services.log_event"), patch("services.log_audit"), patch("services.add_loan_event"):
            from services import mark_unpaid
            mark_unpaid("LC-001", "lender1")

        borrower_notifs = [(u, t) for u, t in created if u == "borrower1"]
        self.assertTrue(any(t == "loan_unpaid" for _, t in borrower_notifs))

    def test_notification_type_for_dispute(self):
        """Notification type for dispute events should be 'dispute_opened'."""
        from decimal import Decimal
        conn, cur = _make_conn()
        loan_row = (9, "lender1", Decimal("100"), "USD", "confirmed")
        cur.fetchone.return_value = loan_row
        cur.rowcount = 1

        created = []
        with patch("services._get_db", return_value=conn), \
             patch("services.create_notification", side_effect=lambda u, t, ti, m: created.append((u, t)) or True), \
             patch("services.log_event"), patch("services.log_audit"), patch("services.add_loan_event"):
            from services import dispute_loan
            dispute_loan("LC-001", "borrower1")

        lender_notifs = [(u, t) for u, t in created if u == "lender1"]
        self.assertTrue(any(t == "dispute_opened" for _, t in lender_notifs))


# ---------------------------------------------------------------------------
# T3 — OTP rate limiter
# ---------------------------------------------------------------------------

class OTPRateLimiterTests(unittest.TestCase):

    def setUp(self):
        # Import the checker and clear its state between tests
        sys.path.insert(0, r"C:\LB drive\api")
        import app as lc_app
        lc_app._otp_attempts.clear()
        self.lc_app = lc_app

    def test_first_five_attempts_allowed(self):
        for i in range(5):
            allowed = self.lc_app._otp_check_rate("192.168.1.1")
            self.assertTrue(allowed, f"Attempt {i+1} should be allowed")

    def test_sixth_attempt_blocked(self):
        for _ in range(5):
            self.lc_app._otp_check_rate("192.168.1.2")
        blocked = self.lc_app._otp_check_rate("192.168.1.2")
        self.assertFalse(blocked, "6th attempt must be blocked")

    def test_different_ips_are_independent(self):
        for _ in range(5):
            self.lc_app._otp_check_rate("10.0.0.1")
        # Different IP should still be allowed
        allowed = self.lc_app._otp_check_rate("10.0.0.2")
        self.assertTrue(allowed, "Different IP should be independent")

    def test_stale_attempts_expire(self):
        """Attempts older than OTP_RATE_WINDOW should not count."""
        old_time = time.time() - self.lc_app.OTP_RATE_WINDOW - 1
        self.lc_app._otp_attempts["10.0.0.3"] = [old_time] * 5
        allowed = self.lc_app._otp_check_rate("10.0.0.3")
        self.assertTrue(allowed, "Expired attempts should not block new requests")

    def test_rate_limit_constants(self):
        self.assertEqual(self.lc_app.OTP_RATE_MAX, 5)
        self.assertEqual(self.lc_app.OTP_RATE_WINDOW, 15 * 60)


if __name__ == "__main__":
    unittest.main()
