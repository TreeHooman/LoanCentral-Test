"""
Tests for T1 (verified lender enforcement) and T2 (session staleness).
"""
import sys
import unittest
from unittest.mock import patch, MagicMock


def _make_conn(rows=None, fetchone_val=None):
    cur = MagicMock()
    cur.fetchone.return_value = fetchone_val
    cur.fetchall.return_value = rows or []
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn, cur


# ---------------------------------------------------------------------------
# T1 — Verified lender enforcement (service layer)
# ---------------------------------------------------------------------------

class VerifiedLenderEnforcementTests(unittest.TestCase):

    def test_verified_lender_can_be_granted(self):
        conn, cur = _make_conn()
        with patch("services._get_db", return_value=conn):
            from services import set_verified_lender
            ok, err = set_verified_lender("lender1", True, "mod1", "All checks passed")
        self.assertTrue(ok)
        self.assertIsNone(err)
        conn.commit.assert_called()

    def test_verified_lender_can_be_revoked(self):
        conn, cur = _make_conn()
        with patch("services._get_db", return_value=conn):
            from services import set_verified_lender
            ok, err = set_verified_lender("lender1", False, "mod1", "Revoked — policy violation")
        self.assertTrue(ok)
        self.assertIsNone(err)
        conn.commit.assert_called()

    def test_get_verified_lender_status_true(self):
        from datetime import datetime
        conn, cur = _make_conn()
        cur.fetchone.return_value = (True, datetime(2026, 1, 1), "mod1", "ok", "lender")
        with patch("services._get_db", return_value=conn):
            from services import get_verified_lender_status
            verified, details, err = get_verified_lender_status("lender1")
        self.assertTrue(verified)
        self.assertEqual(details["verified_by"], "mod1")
        self.assertIsNone(err)

    def test_get_verified_lender_status_unverified(self):
        conn, cur = _make_conn()
        cur.fetchone.return_value = (False, None, None, None, "lender")
        with patch("services._get_db", return_value=conn):
            from services import get_verified_lender_status
            verified, details, err = get_verified_lender_status("lender1")
        self.assertFalse(verified)
        self.assertIsNone(err)

    def test_get_verified_lender_status_not_found(self):
        conn, cur = _make_conn()
        cur.fetchone.return_value = None
        with patch("services._get_db", return_value=conn):
            from services import get_verified_lender_status
            verified, details, err = get_verified_lender_status("nobody")
        self.assertFalse(verified)
        self.assertIsNone(err)

    def test_perm_version_bumped_on_grant(self):
        conn, cur = _make_conn()
        with patch("services._get_db", return_value=conn):
            from services import set_verified_lender
            set_verified_lender("lender1", True, "mod1")
        # perm_version bump must be in the UPDATE statement
        update_calls = [str(c) for c in cur.execute.call_args_list if "perm_version" in str(c).lower()]
        self.assertTrue(len(update_calls) > 0, "perm_version not updated on grant")

    def test_perm_version_bumped_on_revoke(self):
        conn, cur = _make_conn()
        with patch("services._get_db", return_value=conn):
            from services import set_verified_lender
            set_verified_lender("lender1", False, "mod1")
        update_calls = [str(c) for c in cur.execute.call_args_list if "perm_version" in str(c).lower()]
        self.assertTrue(len(update_calls) > 0, "perm_version not updated on revoke")


# ---------------------------------------------------------------------------
# T2 — Session staleness: revoked lender blocked on fresh check
# ---------------------------------------------------------------------------

class SessionStalenessTests(unittest.TestCase):

    def test_fresh_check_returns_false_after_revocation(self):
        """_is_lender_verified_fresh always queries DB — returns False when revoked."""
        conn, cur = _make_conn()
        cur.fetchone.return_value = (False, None, None, None, "lender")
        with patch("services._get_db", return_value=conn):
            from api.app import _is_lender_verified_fresh
            result = _is_lender_verified_fresh("revoked_lender")
        self.assertFalse(result)

    def test_fresh_check_returns_true_for_verified(self):
        from datetime import datetime
        conn, cur = _make_conn()
        cur.fetchone.return_value = (True, datetime(2026, 1, 1), "mod1", "ok", "lender")
        with patch("services._get_db", return_value=conn):
            from api.app import _is_lender_verified_fresh
            result = _is_lender_verified_fresh("verified_lender")
        self.assertTrue(result)

    def test_perm_version_query(self):
        """_get_perm_version returns correct version from DB."""
        conn, cur = _make_conn()
        cur.fetchone.return_value = (5,)
        with patch("services._get_db", return_value=conn):
            from api.app import _get_perm_version
            v = _get_perm_version("lender1")
        self.assertEqual(v, 5)

    def test_perm_version_returns_zero_on_missing(self):
        conn, cur = _make_conn()
        cur.fetchone.return_value = None
        with patch("services._get_db", return_value=conn):
            from api.app import _get_perm_version
            v = _get_perm_version("nobody")
        self.assertEqual(v, 0)


# ---------------------------------------------------------------------------
# T3+T4 — Audit log + loan events wired into core service actions
# ---------------------------------------------------------------------------

class AuditWiringTests(unittest.TestCase):

    def _loan_conn(self):
        """Return a mock conn that satisfies create_loan's DB calls."""
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.side_effect = [None, (42,)]  # duplicate check → None, RETURNING id → 42
        conn.cursor.return_value = cur
        conn.is_sqlite = False
        return conn, cur

    def test_create_loan_calls_log_audit(self):
        from decimal import Decimal
        conn, cur = self._loan_conn()
        with patch("services._get_db", return_value=conn), \
             patch("services.log_audit") as mock_audit, \
             patch("services.add_loan_event") as mock_event, \
             patch("services.log_event"):
            from services import create_loan
            create_loan("lender1", "borrower1", Decimal("100"), "USD",
                        "https://reddit.com/r/test/comments/abc/")
        mock_audit.assert_called()
        call_kwargs = mock_audit.call_args
        self.assertEqual(call_kwargs[0][2], "loan_created")

    def test_create_loan_calls_add_loan_event(self):
        from decimal import Decimal
        conn, cur = self._loan_conn()
        with patch("services._get_db", return_value=conn), \
             patch("services.log_audit"), \
             patch("services.add_loan_event") as mock_event, \
             patch("services.log_event"):
            from services import create_loan
            create_loan("lender1", "borrower1", Decimal("100"), "USD",
                        "https://reddit.com/r/test/comments/abc/")
        mock_event.assert_called()
        call_args = mock_event.call_args[0]
        self.assertEqual(call_args[1], "loan_created")

    def test_role_change_calls_log_audit(self):
        conn, cur = _make_conn()
        cur.fetchone.return_value = ("borrower",)  # old role
        with patch("services._get_db", return_value=conn), \
             patch("services.log_audit") as mock_audit, \
             patch("services.log_event"):
            from services import set_user_role
            set_user_role("user1", "lender", actor="mod1", actor_role="mod")
        mock_audit.assert_called()
        call_args = mock_audit.call_args[0]
        self.assertIn("role", call_args[2])  # action_type contains 'role'


if __name__ == "__main__":
    unittest.main()
