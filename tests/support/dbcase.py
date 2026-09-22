"""Real-database test base class.

Most of the suite replaces the DB connection with a ``MagicMock``, so the SQL is
never executed and dialect errors, constraint violations, and wrong WHERE
clauses all pass silently. ``RealDBTestCase`` runs each test against a throwaway
SQLite file through the same ``local_db`` translation layer the dev dashboard
uses, so a statement that cannot execute fails the test.

Prefer this base class for anything touching loan or request state. Mocks are
still fine for pure-Python validation branches that never reach the database.
"""

import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import services
from local_db import get_sqlite_connection


class RealDBTestCase(unittest.TestCase):
    """Per-test SQLite database, patched into ``services._get_db``."""

    def setUp(self):
        super().setUp()
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.db_path = str(Path(self._temp.name) / "loancentral.sqlite3")
        self.connection = lambda: get_sqlite_connection(self.db_path)

        self.addCleanup(patch.stopall)
        patch.object(services, "_get_db", self.connection).start()

        with patch.dict(os.environ, {"LOANCENTRAL_ENV": "dev", "REDDIT_MODE": "dry_run"}):
            self.web = importlib.import_module("api.app")
        self.web.app.config.update(TESTING=True)
        self.web._api_rate_hits.clear()
        self.client = self.web.app.test_client()

    # -- helpers ------------------------------------------------------------

    def execute(self, sql, params=()):
        """Run a statement and commit. Returns any rows the statement produced."""
        conn = self.connection()
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            try:
                rows = cur.fetchall()
            except Exception:
                rows = []
            conn.commit()
            return rows
        finally:
            conn.close()

    query = execute

    def make_user(self, username, role="borrower", verified_lender=False):
        self.execute(
            "INSERT INTO user_roles (username, role, verified_lender) VALUES (%s, %s, %s)",
            (username, role, bool(verified_lender)),
        )
        return username

    def login(self, username, role="borrower"):
        with self.client.session_transaction() as session:
            session.clear()
            session["username"] = username
            session["role"] = role
        return username

    def logout(self):
        with self.client.session_transaction() as session:
            session.clear()
