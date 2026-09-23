"""The live `loan_requests` table is not the one the code creates.

`_ensure_loan_requests_table` builds a clean table. The production table is a
different thing: the original bot schema, renamed in place by
migrations/migrate_loan_requests.py, still carrying legacy columns — notably
`post_date NOT NULL`, which nothing populated.

Every test in the suite ran against the clean shape, so request creation looked
fine while it could not insert a single row into the real table. Both the bot
import and the dashboard form failed there with a NOT NULL violation. This file
rebuilds the legacy shape and exercises the real code against it.

If the production table turns out to have other legacy columns, add them to
LEGACY_DDL and these tests will say whether the code copes.
"""

from datetime import datetime
from decimal import Decimal

import services
from tests.support.dbcase import RealDBTestCase


#: The shape observed in the migrated dev database (PRAGMA table_info), which
#: was built from the real bot schema rather than from schema.sql.
LEGACY_DDL = """
    CREATE TABLE loan_requests (
        id                          INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id                  VARCHAR(20)  NOT NULL UNIQUE,
        borrower_username           VARCHAR(100) NOT NULL,
        requested_amount            NUMERIC      NOT NULL,
        currency                    TEXT         NOT NULL DEFAULT 'USD',
        requested_repayment_amount  NUMERIC,
        requested_due_date          DATE,
        payment_method              TEXT,
        lender_note                 TEXT,
        expires_at                  TIMESTAMP,
        post_date                   TIMESTAMP    NOT NULL,
        thread_url                  TEXT         NOT NULL,
        reddit_post_id              VARCHAR(30),
        request_status              VARCHAR(30)  NOT NULL DEFAULT 'open',
        funded_by                   TEXT,
        funded_date                 TIMESTAMP,
        loan_id                     TEXT,
        created_at                  TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
        reddit_username             VARCHAR(100),
        reddit_comment_id           VARCHAR(30),
        updated_at                  TIMESTAMP,
        funded_loan_id              INTEGER,
        notes                       TEXT
    )
"""


class LegacyLoanRequestsTableTests(RealDBTestCase):

    TITLE = "[REQ] ($150) (#Reno, NV, USA) (Repay $180) (2027-09-01)"

    def setUp(self):
        super().setUp()
        # Replace the clean table with the legacy one.
        self.execute("DROP TABLE IF EXISTS loan_requests")
        self.execute(LEGACY_DDL)
        self.make_user("lender", role="lender", verified_lender=True)

    def columns(self):
        return {row[1] for row in self.query("PRAGMA table_info(loan_requests)")}

    def test_the_fixture_really_is_the_legacy_shape(self):
        columns = self.columns()
        self.assertIn("post_date", columns)
        self.assertIn("funded_by", columns)

    # -- creation -----------------------------------------------------------

    def test_bot_import_works_against_the_legacy_table(self):
        request_id, error = services.save_loan_request(
            "borrower", self.TITLE, "https://example.com/p", datetime.now(), "legacy1")
        self.assertIsNone(error, error)
        self.assertTrue(request_id)

    def test_bot_import_fills_the_legacy_post_date(self):
        request_id, _ = services.save_loan_request(
            "borrower", self.TITLE, "https://example.com/p", datetime.now(), "legacy2")
        post_date = self.query(
            "SELECT post_date FROM loan_requests WHERE request_id = %s",
            (request_id,))[0][0]
        self.assertIsNotNone(post_date)

    def test_dashboard_creation_works_against_the_legacy_table(self):
        request_id, error = services.create_loan_request(
            borrower_username="borrower", requested_amount=Decimal("150.00"),
            thread_url="https://example.com/y")
        self.assertIsNone(error, error)
        self.assertTrue(request_id)

    def test_dashboard_creation_without_a_thread_url_still_works(self):
        """thread_url is NOT NULL in the legacy table but optional in the API."""
        request_id, error = services.create_loan_request(
            borrower_username="borrower", requested_amount=Decimal("150.00"))
        self.assertIsNone(error, error)
        self.assertTrue(request_id)

    def test_the_api_route_can_create_a_request(self):
        self.make_user("mod", role="mod")
        self.login("mod", role="mod")
        response = self.client.post("/api/loan-requests", json={
            "borrower_username": "borrower", "requested_amount": 150.00,
            "thread_url": "https://example.com/z"})
        self.assertEqual(response.status_code, 201, response.get_json())

    # -- the rest of the lifecycle still works there ------------------------

    def test_funding_works_against_the_legacy_table(self):
        request_id, error = services.save_loan_request(
            "borrower", self.TITLE, "https://example.com/p", datetime.now(), "legacy3")
        self.assertIsNone(error, error)
        loan_id, error = services.fund_loan_request(
            request_id, "lender", 180.0, "2027-09-01")
        self.assertIsNone(error, error)
        status = self.query(
            "SELECT request_status FROM loan_requests WHERE request_id = %s",
            (request_id,))[0][0]
        self.assertEqual(status, "funded")

    def test_status_changes_work_against_the_legacy_table(self):
        request_id, _ = services.save_loan_request(
            "borrower", self.TITLE, "https://example.com/p", datetime.now(), "legacy4")
        ok, error = services.update_request_status(request_id, "expired", actor="mod")
        self.assertIsNone(error, error)
        self.assertTrue(ok)

    def test_reading_a_request_works_against_the_legacy_table(self):
        request_id, _ = services.save_loan_request(
            "borrower", self.TITLE, "https://example.com/p", datetime.now(), "legacy5")
        summary, error = services.get_request_summary(request_id)
        self.assertIsNone(error, error)
        self.assertEqual(summary["borrower"], "borrower")

    def test_duplicate_detection_works_against_the_legacy_table(self):
        services.save_loan_request(
            "borrower", self.TITLE, "https://example.com/p", datetime.now(), "legacy6")
        duplicates, error = services.find_duplicate_open_requests("borrower")
        self.assertIsNone(error, error)


class ColumnIntrospectionTests(RealDBTestCase):

    def test_reports_the_columns_a_table_has(self):
        conn = self.connection()
        try:
            columns = services._table_columns(conn, "loan_requests")
        finally:
            conn.close()
        self.assertIn("request_id", columns)
        self.assertIn("request_status", columns)

    def test_unknown_table_reports_nothing_rather_than_raising(self):
        conn = self.connection()
        try:
            self.assertEqual(services._table_columns(conn, "no_such_table"), set())
        finally:
            conn.close()

    def test_insert_skips_columns_the_table_does_not_have(self):
        conn = self.connection()
        try:
            cur = conn.cursor()
            db_id = services._insert_available(cur, "loan_requests", {
                "request_id": "REQ-COLTEST",
                "borrower_username": "someone",
                "request_status": "open",
                "a_column_that_does_not_exist": "ignored",
            }, services._table_columns(conn, "loan_requests"))
            conn.commit()
        finally:
            conn.close()
        self.assertIsNotNone(db_id)
