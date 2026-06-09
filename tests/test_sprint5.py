"""
Sprint 5 tests — Verification workflow, profile enhancements, global search.
Covers:
  T2  — Verification queue: more_info action, revoke, audit log, notifications,
          reddit_username in list
  T4  — Global search: reddit_username in user results
  T7  — Profile: verified_lender_at and verified_lender_by in get_user_profile
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
# T7 — Profile: verified_lender_at and verified_lender_by
# ---------------------------------------------------------------------------

class ProfileVerificationDetailsTests(unittest.TestCase):

    def test_profile_includes_verified_at_and_by(self):
        conn, cur = _make_conn()
        users_row = (2, 3, "150.00", "300.00", "140.00", 0, "0.00")
        active_row = (1, "100.00")
        verified_at = datetime(2026, 3, 15, 10, 0, 0)
        roles_row = (True, "reddit_name", verified_at, "mod1")
        cur.fetchone.side_effect = [users_row, active_row, roles_row]
        with patch("services._get_db", return_value=conn):
            from services import get_user_profile
            profile, err = get_user_profile("lender1")
        self.assertIsNone(err)
        self.assertTrue(profile["verified_lender"])
        self.assertIsNotNone(profile["verified_lender_at"])
        self.assertEqual(profile["verified_lender_by"], "mod1")
        self.assertIn("2026", profile["verified_lender_at"])

    def test_profile_verified_at_none_when_not_verified(self):
        conn, cur = _make_conn()
        users_row = (0, 0, "0.00", "0.00", "0.00", 0, "0.00")
        active_row = (0, "0.00")
        roles_row = (False, None, None, None)
        cur.fetchone.side_effect = [users_row, active_row, roles_row]
        with patch("services._get_db", return_value=conn):
            from services import get_user_profile
            profile, err = get_user_profile("borrower1")
        self.assertIsNone(err)
        self.assertFalse(profile["verified_lender"])
        self.assertIsNone(profile.get("verified_lender_at"))
        self.assertIsNone(profile.get("verified_lender_by"))


# ---------------------------------------------------------------------------
# T2 — Verification queue: more_info action
# ---------------------------------------------------------------------------

class VerificationMoreInfoTests(unittest.TestCase):

    def _make_verif_conn(self, app_status="pending"):
        conn, cur = _make_conn()
        app_row = (1, "applicant1", "lender", app_status)
        cur.fetchone.return_value = app_row
        cur.rowcount = 1
        return conn, cur

    def test_more_info_accepted_as_valid_decision(self):
        conn, cur = self._make_verif_conn("pending")
        notified = []
        with patch("services._get_db", return_value=conn), \
             patch("services.log_event"), \
             patch("services.log_audit"), \
             patch("services.create_notification",
                   side_effect=lambda u, t, ti, m: notified.append((u, t)) or True):
            from services import decide_verification_application
            result, err = decide_verification_application(1, "more_info", "mod1", "Need bank statement")
        self.assertIsNone(err)
        self.assertEqual(result["decision"], "more_info")

    def test_more_info_notifies_applicant(self):
        conn, cur = self._make_verif_conn("pending")
        notified = []
        with patch("services._get_db", return_value=conn), \
             patch("services.log_event"), \
             patch("services.log_audit"), \
             patch("services.create_notification",
                   side_effect=lambda u, t, ti, m: notified.append((u, t)) or True):
            from services import decide_verification_application
            decide_verification_application(1, "more_info", "mod1", "Please provide more context")
        types = [t for _, t in notified]
        self.assertIn("verification_more_info", types)
        users = [u for u, _ in notified]
        self.assertIn("applicant1", users)

    def test_approved_notifies_applicant(self):
        conn, cur = self._make_verif_conn("pending")
        notified = []
        with patch("services._get_db", return_value=conn), \
             patch("services.log_event"), \
             patch("services.log_audit"), \
             patch("services.set_user_role", return_value=(True, None)), \
             patch("services.set_verified_lender", return_value=(True, None)), \
             patch("services.enqueue_reddit_action"), \
             patch("services.create_notification",
                   side_effect=lambda u, t, ti, m: notified.append((u, t)) or True):
            from services import decide_verification_application
            decide_verification_application(1, "approved", "mod1", "Approved")
        types = [t for u, t in notified if u == "applicant1"]
        self.assertIn("verification_approved", types)

    def test_denied_notifies_applicant(self):
        conn, cur = self._make_verif_conn("pending")
        notified = []
        with patch("services._get_db", return_value=conn), \
             patch("services.log_event"), \
             patch("services.log_audit"), \
             patch("services.create_notification",
                   side_effect=lambda u, t, ti, m: notified.append((u, t)) or True):
            from services import decide_verification_application
            decide_verification_application(1, "denied", "mod1", "Not enough activity")
        types = [t for u, t in notified if u == "applicant1"]
        self.assertIn("verification_denied", types)

    def test_invalid_decision_rejected(self):
        conn, cur = self._make_verif_conn()
        with patch("services._get_db", return_value=conn):
            from services import decide_verification_application
            result, err = decide_verification_application(1, "maybe", "mod1")
        self.assertIsNone(result)
        self.assertIn("approved, denied, or more_info", err)

    def test_already_approved_cannot_be_re_approved(self):
        conn, cur = self._make_verif_conn("approved")
        with patch("services._get_db", return_value=conn), \
             patch("services.log_event"), patch("services.log_audit"), \
             patch("services.create_notification"):
            from services import decide_verification_application
            result, err = decide_verification_application(1, "approved", "mod1")
        self.assertIsNone(result)
        self.assertIsNotNone(err)


# ---------------------------------------------------------------------------
# T2 — Verification queue: audit log wiring
# ---------------------------------------------------------------------------

class VerificationAuditTests(unittest.TestCase):

    def test_approved_creates_audit_entry(self):
        conn, cur = _make_conn()
        cur.fetchone.return_value = (1, "applicant1", "lender", "pending")
        cur.rowcount = 1
        audit_calls = []
        with patch("services._get_db", return_value=conn), \
             patch("services.log_event"), \
             patch("services.set_user_role", return_value=(True, None)), \
             patch("services.set_verified_lender", return_value=(True, None)), \
             patch("services.enqueue_reddit_action"), \
             patch("services.create_notification"), \
             patch("services.log_audit",
                   side_effect=lambda *a, **kw: audit_calls.append(a) or True):
            from services import decide_verification_application
            decide_verification_application(1, "approved", "mod1")
        actions = [a[2] for a in audit_calls]  # a[2] = action string
        self.assertIn("verification_approved", actions)

    def test_denied_creates_audit_entry(self):
        conn, cur = _make_conn()
        cur.fetchone.return_value = (1, "applicant1", "lender", "pending")
        cur.rowcount = 1
        audit_calls = []
        with patch("services._get_db", return_value=conn), \
             patch("services.log_event"), \
             patch("services.create_notification"), \
             patch("services.log_audit",
                   side_effect=lambda *a, **kw: audit_calls.append(a) or True):
            from services import decide_verification_application
            decide_verification_application(1, "denied", "mod1")
        actions = [a[2] for a in audit_calls]
        self.assertIn("verification_denied", actions)

    def test_more_info_creates_audit_entry(self):
        conn, cur = _make_conn()
        cur.fetchone.return_value = (1, "applicant1", "lender", "pending")
        cur.rowcount = 1
        audit_calls = []
        with patch("services._get_db", return_value=conn), \
             patch("services.log_event"), \
             patch("services.create_notification"), \
             patch("services.log_audit",
                   side_effect=lambda *a, **kw: audit_calls.append(a) or True):
            from services import decide_verification_application
            decide_verification_application(1, "more_info", "mod1", "Need docs")
        actions = [a[2] for a in audit_calls]
        self.assertIn("verification_more_info_requested", actions)


# ---------------------------------------------------------------------------
# T2 — Verification list: includes reddit_username
# ---------------------------------------------------------------------------

class VerificationListTests(unittest.TestCase):

    def test_list_includes_reddit_username(self):
        from datetime import datetime
        fake_row = (1, "applicant1", "lender", "pending", "Public note", None,
                    None, None, datetime(2026, 6, 1), None, "reddit_user1", False)
        conn, cur = _make_conn(rows=[fake_row])
        with patch("services._get_db", return_value=conn):
            from services import list_verification_applications
            rows, err = list_verification_applications()
        self.assertIsNone(err)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reddit_username"], "reddit_user1")
        self.assertFalse(rows[0]["already_verified"])

    def test_list_no_db(self):
        with patch("services._get_db", return_value=None):
            from services import list_verification_applications
            rows, err = list_verification_applications()
        self.assertIsNone(rows)
        self.assertIsNotNone(err)


# ---------------------------------------------------------------------------
# T4 — Global search: users include reddit_username
# ---------------------------------------------------------------------------

class GlobalSearchRedditTests(unittest.TestCase):

    def test_user_results_include_reddit_username(self):
        from datetime import datetime
        fake_user = ("alice", "lender", True, datetime(2026, 1, 1), "alice_reddit")
        conn, cur = _make_conn(rows=[fake_user])
        cur.fetchone.return_value = (0,)  # loan count
        cur.fetchall.side_effect = [[], [fake_user]]  # loans=[], users=[fake_user]
        with patch("services._get_db", return_value=conn):
            from services import global_search
            results, total, err = global_search("alice", search_type="users")
        self.assertIsNone(err)
        if results.get("users"):
            user = results["users"][0]
            self.assertIn("reddit_username", user)

    def test_search_by_reddit_username_reaches_db(self):
        """Querying by reddit username should include OR clause in SQL."""
        conn, cur = _make_conn(rows=[])
        cur.fetchone.return_value = (0,)
        cur.fetchall.return_value = []
        with patch("services._get_db", return_value=conn):
            from services import global_search
            global_search("some_reddit_name", search_type="users")
        # Verify the reddit_username column appears in one of the queries
        all_sql = " ".join(str(c.args[0]) for c in cur.execute.call_args_list)
        self.assertIn("reddit_username", all_sql)


if __name__ == "__main__":
    unittest.main()
