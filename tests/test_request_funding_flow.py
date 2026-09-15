"""Offline integration coverage for Reddit request -> dashboard -> loan."""
import importlib
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import services
from local_db import get_sqlite_connection


class RequestFundingFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = str(Path(self.temp.name) / "requests.sqlite3")
        self.connection = lambda: get_sqlite_connection(self.db_path)
        conn = self.connection()
        cur = conn.cursor()
        for name in ("lender", "second_lender"):
            cur.execute("INSERT INTO user_roles (username, role, verified_lender) VALUES (%s, 'lender', TRUE)", (name,))
        conn.commit()
        conn.close()
        self.addCleanup(patch.stopall)
        patch.object(services, "_get_db", self.connection).start()
        with patch.dict(os.environ, {"LOANCENTRAL_ENV": "dev", "REDDIT_MODE": "dry_run"}):
            self.web = importlib.import_module("api.app")
        self.web.app.config.update(TESTING=True)
        self.web._api_rate_hits.clear()
        self.client = self.web.app.test_client()
        self.login()

    def login(self, name="lender", role="lender"):
        with self.client.session_transaction() as session:
            session.clear()
            session["username"] = name
            session["role"] = role

    def query(self, sql, params=()):
        conn = self.connection()
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
            conn.commit()
            return rows
        finally:
            conn.close()

    def make_request(self, title="[REQ] (150 CAD) (Repay 180 CAD) (2027-01-15) (Interac)"):
        code, error = services.save_loan_request(
            "borrower", title, "https://example.com/test-request", datetime.now(), "testpost")
        self.assertIsNone(error)
        return code

    def fund(self, code, **overrides):
        data = {"repay_amount": "180.00", "repay_date": "2027-01-15"}
        data.update(overrides)
        return self.client.post(f"/api/requests/{code}/fund", json=data)

    def test_lookup_fund_track_and_repay(self):
        code = self.make_request()
        request = self.client.get(f"/api/requests/{code[4:].lower()}").get_json()
        self.assertEqual((request["currency"], request["payment_method"]), ("CAD", "Interac"))
        response = self.fund(code)
        self.assertEqual(response.status_code, 200, response.get_json())
        paid_id = response.get_json()["paid_id"]
        loan = self.query("SELECT id, lender, borrower, amount, currency, repay_amount, payment_method FROM loans")[0]
        self.assertEqual(loan[1:], ("lender", "borrower", 150, "CAD", 180, "Interac"))
        self.assertEqual(self.query("SELECT request_status, funded_loan_id FROM loan_requests"), [("funded", loan[0])])
        self.assertEqual(self.query("SELECT event_type FROM audit_events WHERE request_id = %s AND event_type = 'request_funded'", (code,)), [("request_funded",)])
        result, error = services.mark_repaid(paid_id, Decimal("180"), "CAD", "lender")
        self.assertIsNone(error)
        self.assertEqual(self.query("SELECT status FROM loans"), [("repaid",)])

    def test_repeat_and_other_lender_cannot_fund_twice(self):
        code = self.make_request()
        self.assertEqual(self.fund(code).status_code, 200)
        self.login("second_lender")
        self.assertEqual(self.fund(code).status_code, 400)
        self.assertEqual(self.query("SELECT COUNT(*) FROM loans"), [(1,)])

    def test_two_concurrent_funders_create_only_one_loan(self):
        code = self.make_request()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda name: services.fund_loan_request(code, name, 180, "2027-01-15"), ["lender", "second_lender"]))
        self.assertEqual(sum(error is None for _, error in results), 1, results)
        self.assertEqual(self.query("SELECT COUNT(*) FROM loans"), [(1,)])

    def test_failed_request_link_rolls_back_loan_and_stats(self):
        code = self.make_request()
        self.query("CREATE TRIGGER fail_link BEFORE UPDATE OF funded_loan_id ON loan_requests BEGIN SELECT RAISE(ABORT, 'test link failure'); END")
        self.assertEqual(self.fund(code).status_code, 400)
        self.assertEqual(self.query("SELECT COUNT(*) FROM loans"), [(0,)])
        self.assertEqual(self.query("SELECT COUNT(*) FROM users"), [(0,)])
        self.assertEqual(self.query("SELECT request_status FROM loan_requests"), [("open",)])

    def test_failed_audit_rolls_back_funding(self):
        code = self.make_request()
        self.query("CREATE TRIGGER fail_audit BEFORE INSERT ON audit_events WHEN NEW.event_type = 'request_funded' BEGIN SELECT RAISE(ABORT, 'test audit failure'); END")
        self.assertEqual(self.fund(code).status_code, 400)
        self.assertEqual(self.query("SELECT COUNT(*) FROM loans"), [(0,)])
        self.assertEqual(self.query("SELECT request_status FROM loan_requests"), [("open",)])

    def test_public_id_collision_retries_without_losing_request_lock(self):
        code = self.make_request()
        self.query("INSERT INTO loans (loan_id, lender, borrower, amount, currency, date_created, original_thread) VALUES ('123', 'other', 'someone', 1, 'USD', NOW(), 'test') RETURNING id")
        with patch.object(services, "_generate_loan_id", side_effect=["123", "456"]):
            response = self.fund(code)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["paid_id"], "456")
        self.assertEqual(self.query("SELECT request_status FROM loan_requests"), [("funded",)])

    def test_expired_request_and_linked_self_loan_rejected(self):
        code = self.make_request()
        self.query("UPDATE user_roles SET reddit_username = 'borrower' WHERE username = 'lender' RETURNING username")
        self.assertIn("yourself", self.fund(code).get_json()["error"])
        self.login("second_lender")
        self.query("UPDATE loan_requests SET notes = 'expires:2000-01-01' RETURNING request_id")
        self.assertIn("expired", self.fund(code).get_json()["error"])
        self.assertEqual(self.query("SELECT COUNT(*) FROM loans"), [(0,)])

    def test_generated_code_works_in_reddit_fund_parser(self):
        from commands.fund_command import _parse_fund
        code = self.make_request()
        self.assertEqual(_parse_fund(f"$fund {code} 180 CAD 2027-01-15")[0], code)

    def test_manual_form_cannot_bypass_lender_permissions(self):
        self.login("borrower", "borrower")
        response = self.client.post("/api/loans/create", json={"borrower": "someone", "amount": 150})
        self.assertEqual(response.status_code, 403)

    def test_borrower_unverified_and_impersonation_rejected(self):
        code = self.make_request()
        self.assertEqual(self.fund(code, lender="second_lender").status_code, 403)
        self.login("borrower", "borrower")
        self.assertEqual(self.fund(code).status_code, 403)
        self.login("unverified")
        self.assertEqual(self.fund(code).status_code, 403)
        self.assertEqual(self.query("SELECT COUNT(*) FROM loans"), [(0,)])

    def test_invalid_terms_leave_request_open(self):
        code = self.make_request()
        for value in ("NaN", "Infinity", "nope", -1, [], True):
            self.assertEqual(self.fund(code, repay_amount=value).status_code, 400)
        self.assertEqual(self.fund(code, repay_date="not-a-date").status_code, 400)
        self.assertEqual(self.query("SELECT request_status FROM loan_requests"), [("open",)])

    def test_legacy_numeric_code_still_works(self):
        code = self.make_request()
        self.query("UPDATE loan_requests SET request_id = 'REQ-3841' WHERE request_id = %s RETURNING request_id", (code,))
        self.assertEqual(self.client.get("/api/requests/3841").get_json()["request_id"], "REQ-3841")
        self.assertEqual(self.fund("3841").status_code, 200)

    def test_link_survives_login(self):
        with self.client.session_transaction() as session:
            session.clear()
        self.assertEqual(self.client.get("/record-request/3841").location, "/login")
        with self.client.session_transaction() as session:
            self.assertEqual(session["pending_fund_request"], "REQ-3841")
            session["username"] = "lender"
            session["role"] = "lender"
        page = self.client.get("/dashboard/lender")
        self.assertIn(b'openNewLoanModal("REQ-3841")', page.data)
        with self.client.session_transaction() as session:
            self.assertNotIn("pending_fund_request", session)

    def test_post_reply_includes_request_link_without_network(self):
        import sys
        from tests.support.fakes import FakeDb, FakeSubmission, fake_utils_module
        with patch.dict(sys.modules, {"utils": fake_utils_module(FakeDb())}):
            bot = importlib.import_module("main")
        post = FakeSubmission(author_name="borrower")
        post.id = "testpost"
        post.replies = []
        post.reply = post.replies.append
        post.title = "[REQ] ($150) (Repay $180) (2027-01-15)"
        with patch.object(bot, "generate_user_info", return_value="No loan history."), patch.object(bot, "reddit_limiter"):
            bot.handle_new_post(post)
        code = self.query("SELECT request_id FROM loan_requests")[0][0]
        self.assertIn(f"/record-request/{code}", post.replies[0])
        self.assertIn("No loan history.", post.replies[0])


if __name__ == "__main__":
    unittest.main()
