"""Phase 1 — database-level integrity constraints.

These run against a real SQLite database through local_db, so a constraint that
does not actually exist fails the test. The Postgres equivalents come from
scripts/migrations/013_integrity_constraints.sql.
"""

import sqlite3
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import services
from tests.support.dbcase import RealDBTestCase


class LoanRequestUniquenessTests(RealDBTestCase):

    def test_reddit_post_id_is_unique(self):
        services.create_loan_request(borrower_username="borrower",
                                     reddit_post_id="abc123")
        with self.assertRaises(sqlite3.IntegrityError):
            self.execute(
                "INSERT INTO loan_requests (request_id, borrower_username, reddit_post_id) "
                "VALUES (%s, %s, %s)", ("REQ-DUPE", "someone", "abc123"))

    def test_null_reddit_post_id_is_not_constrained(self):
        """Dashboard-created requests have no Reddit post; many may coexist."""
        for _ in range(3):
            request_id, error = services.create_loan_request(borrower_username="borrower")
            self.assertIsNone(error)
            self.assertTrue(request_id)
        count = self.query("SELECT COUNT(*) FROM loan_requests")[0][0]
        self.assertEqual(count, 3)

    def test_two_requests_cannot_claim_the_same_loan(self):
        self.make_user("lender", role="lender", verified_lender=True)
        loan_id, error = services.create_loan(
            lender="lender", borrower="borrower", amount=Decimal("100.00"),
            currency="USD", thread_url="https://example.com/t",
            repay_amount=Decimal("110.00"), repay_date="2027-01-01")
        self.assertIsNone(error)
        db_id = self.query("SELECT id FROM loans WHERE loan_id = %s", (loan_id,))[0][0]

        first, _ = services.create_loan_request(borrower_username="borrower")
        second, _ = services.create_loan_request(borrower_username="borrower")
        self.execute("UPDATE loan_requests SET funded_loan_id = %s WHERE request_id = %s",
                     (db_id, first))
        with self.assertRaises(sqlite3.IntegrityError):
            self.execute("UPDATE loan_requests SET funded_loan_id = %s WHERE request_id = %s",
                         (db_id, second))


class DuplicateImportIsIdempotentTests(RealDBTestCase):
    """The bot re-importing a post must return the existing request, not fail."""

    TITLE = "[REQ] ($150) (#Springfield, IL, USA) (Repay $180) (2027-03-01)"

    def test_reimporting_the_same_post_returns_the_same_request(self):
        first, error = services.save_loan_request(
            "borrower", self.TITLE, "https://example.com/p", datetime.now(), "post1")
        self.assertIsNone(error)
        second, error = services.save_loan_request(
            "borrower", self.TITLE, "https://example.com/p", datetime.now(), "post1")
        self.assertIsNone(error)
        self.assertEqual(first, second)
        self.assertEqual(self.query("SELECT COUNT(*) FROM loan_requests")[0][0], 1)

    def test_race_losing_insert_returns_the_winners_request(self):
        """Simulates the dedup SELECT passing before the other insert commits."""
        winner, error = services.save_loan_request(
            "borrower", self.TITLE, "https://example.com/p", datetime.now(), "post2")
        self.assertIsNone(error)

        real_execute = services._get_db

        class BlindCursor:
            """Reports 'no existing row' so the insert races the unique index."""
            def __init__(self, inner):
                self._inner = inner
                self._skip_next_fetch = False

            def execute(self, sql, params=None):
                self._skip_next_fetch = "SELECT request_id FROM loan_requests" in sql
                if self._skip_next_fetch:
                    return self
                return self._inner.execute(sql, params)

            def fetchone(self):
                if self._skip_next_fetch:
                    self._skip_next_fetch = False
                    return None
                return self._inner.fetchone()

            def __getattr__(self, name):
                return getattr(self._inner, name)

        class BlindConn:
            is_sqlite = True

            def __init__(self, inner):
                self._inner = inner
                self._blind = True

            def cursor(self):
                inner_cursor = self._inner.cursor()
                if self._blind:
                    self._blind = False      # only the dedup lookup is blinded
                    return BlindCursor(inner_cursor)
                return inner_cursor

            def __getattr__(self, name):
                return getattr(self._inner, name)

        services._get_db = lambda: BlindConn(real_execute())
        try:
            loser, error = services.save_loan_request(
                "borrower", self.TITLE, "https://example.com/p", datetime.now(), "post2")
        finally:
            services._get_db = real_execute

        self.assertIsNone(error, "a lost race must not surface as an error")
        self.assertEqual(loser, winner)
        self.assertEqual(self.query("SELECT COUNT(*) FROM loan_requests")[0][0], 1)


class MigrationRunnerTests(unittest.TestCase):
    """The statement splitter has to keep `DO $$ ... $$` blocks intact."""

    def setUp(self):
        import importlib.util
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location(
            "run_migrations", root / "scripts" / "run_migrations.py")
        self.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runner)
        self.migrations = root / "scripts" / "migrations"

    def test_dollar_quoted_block_is_one_statement(self):
        sql = (self.migrations / "013_integrity_constraints.sql").read_text(encoding="utf-8")
        statements = self.runner.split_sql(sql)
        do_blocks = [s for s in statements if s.lstrip().upper().startswith("DO")]
        self.assertEqual(len(do_blocks), 1)
        self.assertEqual(do_blocks[0].count("$$"), 2,
                         "the DO block was split across statements")
        self.assertIn("ck_lr_status", do_blocks[0])

    def test_semicolons_inside_string_literals_do_not_split(self):
        statements = self.runner.split_sql("SELECT 'a;b'; SELECT 2;")
        self.assertEqual(len(statements), 2)
        self.assertIn("'a;b'", statements[0])

    def test_comments_are_stripped(self):
        statements = self.runner.split_sql("-- a comment;\nSELECT 1;")
        self.assertEqual(len(statements), 1)
        self.assertNotIn("comment", statements[0])

    def test_every_migration_file_parses(self):
        for path in sorted(self.migrations.glob("*.sql")):
            statements = self.runner.split_sql(path.read_text(encoding="utf-8"))
            self.assertTrue(statements, f"{path.name} produced no statements")

    def test_checksums_are_stable(self):
        path = self.migrations / "012_schema_migrations.sql"
        self.assertEqual(self.runner.checksum(path), self.runner.checksum(path))
