"""
Power Sprint tests — Admin hub, mod investigation, dispute center,
mod notes system, risk indicators.
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
# Mod notes service tests
# =============================================================================

class ModNotesServiceTests(unittest.TestCase):

    def test_create_note_valid(self):
        from services import create_mod_note
        conn, cur = _make_conn(fetchone_val=(10,))
        with patch("services._get_db", return_value=conn):
            nid, err = create_mod_note("alice", "mod1", "general", "Test note")
        self.assertIsNone(err)
        self.assertEqual(nid, 10)
        conn.commit.assert_called()

    def test_create_note_invalid_category(self):
        from services import create_mod_note
        nid, err = create_mod_note("alice", "mod1", "banana", "content")
        self.assertIsNone(nid)
        self.assertIn("Invalid category", err)

    def test_create_note_all_valid_categories(self):
        from services import create_mod_note
        for cat in ("general", "verification", "dispute", "investigation", "warning"):
            conn, cur = _make_conn(fetchone_val=(1,))
            with patch("services._get_db", return_value=conn):
                nid, err = create_mod_note("alice", "mod1", cat, "content")
            self.assertIsNone(err, f"category {cat} should be valid")

    def test_create_note_empty_content(self):
        from services import create_mod_note
        nid, err = create_mod_note("alice", "mod1", "general", "  ")
        self.assertIsNone(nid)
        self.assertIn("Content", err)

    def test_create_note_missing_author(self):
        from services import create_mod_note
        nid, err = create_mod_note("alice", "", "general", "content")
        self.assertIsNone(nid)
        self.assertIsNotNone(err)

    def test_create_note_truncates_long_content(self):
        from services import create_mod_note
        conn, cur = _make_conn(fetchone_val=(1,))
        long_content = "x" * 3000
        with patch("services._get_db", return_value=conn):
            nid, err = create_mod_note("alice", "mod1", "general", long_content)
        self.assertIsNone(err)
        args = cur.execute.call_args_list[-1][0][1]
        self.assertLessEqual(len(args[3]), 2000)

    def test_create_note_db_failure(self):
        from services import create_mod_note
        with patch("services._get_db", return_value=None):
            nid, err = create_mod_note("alice", "mod1", "general", "content")
        self.assertIsNone(nid)
        self.assertIn("Database", err)

    def test_get_mod_notes_returns_list(self):
        from services import get_mod_notes
        now = datetime(2026, 6, 10, 12, 0)
        conn, cur = _make_conn(rows=[
            (1, "alice", "mod1", "general", "A note", False, now, now),
        ])
        with patch("services._get_db", return_value=conn):
            notes, err = get_mod_notes("alice")
        self.assertIsNone(err)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["author"], "mod1")
        self.assertIsInstance(notes[0]["created_at"], str)

    def test_get_mod_notes_empty(self):
        from services import get_mod_notes
        conn, cur = _make_conn(rows=[])
        with patch("services._get_db", return_value=conn):
            notes, err = get_mod_notes("nobody")
        self.assertIsNone(err)
        self.assertEqual(notes, [])

    def test_get_mod_notes_db_failure(self):
        from services import get_mod_notes
        with patch("services._get_db", return_value=None):
            notes, err = get_mod_notes("alice")
        self.assertEqual(notes, [])
        self.assertIsNotNone(err)

    def test_update_mod_note_success(self):
        from services import update_mod_note
        conn, cur = _make_conn(rowcount=1)
        with patch("services._get_db", return_value=conn):
            ok, err = update_mod_note(1, "Updated content", "mod1")
        self.assertTrue(ok)
        self.assertIsNone(err)
        conn.commit.assert_called()

    def test_update_mod_note_empty_content(self):
        from services import update_mod_note
        ok, err = update_mod_note(1, "  ", "mod1")
        self.assertFalse(ok)
        self.assertIn("Content", err)

    def test_update_mod_note_not_found(self):
        from services import update_mod_note
        conn, cur = _make_conn(rowcount=0)
        with patch("services._get_db", return_value=conn):
            ok, err = update_mod_note(999, "content", "mod1")
        self.assertFalse(ok)
        self.assertIn("not found", err)

    def test_archive_mod_note_success(self):
        from services import archive_mod_note
        conn, cur = _make_conn(rowcount=1)
        with patch("services._get_db", return_value=conn):
            ok, err = archive_mod_note(1, "mod1")
        self.assertTrue(ok)
        self.assertIsNone(err)
        conn.commit.assert_called()

    def test_archive_mod_note_not_found(self):
        from services import archive_mod_note
        conn, cur = _make_conn(rowcount=0)
        with patch("services._get_db", return_value=conn):
            ok, err = archive_mod_note(999, "mod1")
        self.assertFalse(ok)
        self.assertIn("not found", err)

    def test_archive_mod_note_db_failure(self):
        from services import archive_mod_note
        with patch("services._get_db", return_value=None):
            ok, err = archive_mod_note(1, "mod1")
        self.assertFalse(ok)
        self.assertIsNotNone(err)


# =============================================================================
# Disputed loans service tests
# =============================================================================

class DisputedLoansServiceTests(unittest.TestCase):

    def test_get_disputed_loans_returns_list(self):
        from services import get_disputed_loans
        now = datetime(2026, 6, 10, 12, 0)
        conn, cur = _make_conn(rows=[
            (1, "LC-001", "lender1", "borrower1", 100.0, "USD", now, "http://r.co/t", None),
        ])
        with patch("services._get_db", return_value=conn):
            loans, err = get_disputed_loans()
        self.assertIsNone(err)
        self.assertEqual(len(loans), 1)
        self.assertEqual(loans[0]["lender"], "lender1")
        self.assertEqual(loans[0]["loan_id"], "LC-001")
        self.assertIsInstance(loans[0]["date_created"], str)

    def test_get_disputed_loans_empty(self):
        from services import get_disputed_loans
        conn, cur = _make_conn(rows=[])
        with patch("services._get_db", return_value=conn):
            loans, err = get_disputed_loans()
        self.assertIsNone(err)
        self.assertEqual(loans, [])

    def test_get_disputed_loans_db_failure(self):
        from services import get_disputed_loans
        with patch("services._get_db", return_value=None):
            loans, err = get_disputed_loans()
        self.assertIsNone(loans)
        self.assertIsNotNone(err)

    def test_get_disputed_loans_uses_db_id_as_fallback(self):
        from services import get_disputed_loans
        now = datetime(2026, 6, 10)
        conn, cur = _make_conn(rows=[
            (42, None, "lender1", "borrower1", 50.0, "USD", now, None, None),
        ])
        with patch("services._get_db", return_value=conn):
            loans, err = get_disputed_loans()
        self.assertIsNone(err)
        self.assertEqual(loans[0]["loan_id"], "42")


# =============================================================================
# Risk indicators service tests
# =============================================================================

class RiskIndicatorsServiceTests(unittest.TestCase):

    def test_get_risk_indicators_structure(self):
        from services import get_risk_indicators
        conn, cur = _make_conn(rows=[
            ("alice", 2, 1, 3, 8),
            ("bob",   1, 0, 1, 4),
        ])
        with patch("services._get_db", return_value=conn):
            rows, err = get_risk_indicators()
        self.assertIsNone(err)
        self.assertEqual(len(rows), 2)
        self.assertIn("disputes", rows[0])
        self.assertIn("unpaid",   rows[0])
        self.assertIn("active",   rows[0])
        self.assertEqual(rows[0]["username"], "alice")
        self.assertEqual(rows[0]["disputes"], 2)

    def test_get_risk_indicators_empty(self):
        from services import get_risk_indicators
        conn, cur = _make_conn(rows=[])
        with patch("services._get_db", return_value=conn):
            rows, err = get_risk_indicators()
        self.assertIsNone(err)
        self.assertEqual(rows, [])

    def test_get_risk_indicators_db_failure(self):
        from services import get_risk_indicators
        with patch("services._get_db", return_value=None):
            rows, err = get_risk_indicators()
        self.assertIsNone(rows)
        self.assertIsNotNone(err)


# =============================================================================
# API route tests
# =============================================================================

class ModNotesAPITests(unittest.TestCase):

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

    def _lender_client(self):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["username"] = "lender1"
            sess["role"]     = "lender"
        return client

    def test_get_notes_mod_access(self):
        conn, cur = _make_conn(rows=[])
        with patch("services._get_db", return_value=conn):
            res = self._mod_client().get("/api/mod/notes/alice")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("notes", data)

    def test_get_notes_requires_mod(self):
        conn, cur = _make_conn(rows=[])
        with patch("services._get_db", return_value=conn):
            res = self._lender_client().get("/api/mod/notes/alice")
        self.assertIn(res.status_code, (302, 403))

    def test_get_notes_unauthenticated(self):
        res = self.app.test_client().get("/api/mod/notes/alice")
        self.assertIn(res.status_code, (302, 401, 403))

    def test_create_note_success(self):
        conn, cur = _make_conn(fetchone_val=(5,))
        with patch("services._get_db", return_value=conn):
            res = self._mod_client().post("/api/mod/notes/alice",
                json={"category": "general", "content": "Test note"})
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertIn("id", data)

    def test_create_note_invalid_category(self):
        conn, cur = _make_conn(fetchone_val=(1,))
        with patch("services._get_db", return_value=conn):
            res = self._mod_client().post("/api/mod/notes/alice",
                json={"category": "garbage", "content": "content"})
        self.assertEqual(res.status_code, 400)

    def test_create_note_empty_content(self):
        conn, cur = _make_conn(fetchone_val=(1,))
        with patch("services._get_db", return_value=conn):
            res = self._mod_client().post("/api/mod/notes/alice",
                json={"category": "general", "content": ""})
        self.assertEqual(res.status_code, 400)

    def test_update_note_success(self):
        conn, cur = _make_conn(rowcount=1)
        with patch("services._get_db", return_value=conn):
            res = self._mod_client().patch("/api/mod/notes/1",
                json={"content": "Updated content"})
        self.assertEqual(res.status_code, 200)

    def test_update_note_not_found(self):
        conn, cur = _make_conn(rowcount=0)
        with patch("services._get_db", return_value=conn):
            res = self._mod_client().patch("/api/mod/notes/999",
                json={"content": "Updated content"})
        self.assertEqual(res.status_code, 400)

    def test_archive_note_success(self):
        conn, cur = _make_conn(rowcount=1)
        with patch("services._get_db", return_value=conn):
            res = self._mod_client().delete("/api/mod/notes/1")
        self.assertEqual(res.status_code, 200)

    def test_archive_note_not_found(self):
        conn, cur = _make_conn(rowcount=0)
        with patch("services._get_db", return_value=conn):
            res = self._mod_client().delete("/api/mod/notes/999")
        self.assertEqual(res.status_code, 400)


class DisputeAPITests(unittest.TestCase):

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

    def test_disputes_api_mod_access(self):
        conn, cur = _make_conn(rows=[])
        with patch("services._get_db", return_value=conn):
            res = self._mod_client().get("/api/mod/disputes")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("disputes", data)
        self.assertIn("total", data)

    def test_disputes_requires_mod(self):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["username"] = "borrower1"
            sess["role"]     = "borrower"
        res = client.get("/api/mod/disputes")
        self.assertIn(res.status_code, (302, 403))

    def test_risk_api_mod_access(self):
        conn, cur = _make_conn(rows=[])
        with patch("services._get_db", return_value=conn):
            res = self._mod_client().get("/api/mod/risk")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("indicators", data)


class PageRenderPowerSprintTests(unittest.TestCase):

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

    def _admin_client(self):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["username"] = "admin1"
            sess["role"]     = "admin"
        return client

    def _lender_client(self):
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["username"] = "lender1"
            sess["role"]     = "lender"
        return client

    def test_admin_hub_loads_for_mod(self):
        conn, cur = _make_conn()
        with patch("services._get_db", return_value=conn):
            res = self._mod_client().get("/admin")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Admin Command Center", res.data)

    def test_admin_hub_loads_for_admin(self):
        conn, cur = _make_conn()
        with patch("services._get_db", return_value=conn):
            res = self._admin_client().get("/admin")
        self.assertEqual(res.status_code, 200)

    def test_admin_hub_redirects_for_lender(self):
        conn, cur = _make_conn()
        with patch("services._get_db", return_value=conn):
            res = self._lender_client().get("/admin")
        self.assertEqual(res.status_code, 302)

    def test_investigation_page_loads_for_mod(self):
        conn, cur = _make_conn(rows=[])
        with patch("services._get_db", return_value=conn):
            res = self._mod_client().get("/dashboard/mod/investigation/alice")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"alice", res.data)

    def test_investigation_redirects_for_lender(self):
        conn, cur = _make_conn(rows=[])
        with patch("services._get_db", return_value=conn):
            res = self._lender_client().get("/dashboard/mod/investigation/alice")
        self.assertEqual(res.status_code, 302)

    def test_disputes_page_loads_for_mod(self):
        conn, cur = _make_conn()
        with patch("services._get_db", return_value=conn):
            res = self._mod_client().get("/dashboard/mod/disputes")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Dispute Center", res.data)

    def test_disputes_page_redirects_for_lender(self):
        conn, cur = _make_conn()
        with patch("services._get_db", return_value=conn):
            res = self._lender_client().get("/dashboard/mod/disputes")
        self.assertEqual(res.status_code, 302)

    def test_risk_page_loads_for_mod(self):
        conn, cur = _make_conn()
        with patch("services._get_db", return_value=conn):
            res = self._mod_client().get("/dashboard/mod/risk")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Risk Review", res.data)

    def test_unauthenticated_redirected_from_admin(self):
        res = self.app.test_client().get("/admin")
        self.assertEqual(res.status_code, 302)


if __name__ == "__main__":
    unittest.main()
