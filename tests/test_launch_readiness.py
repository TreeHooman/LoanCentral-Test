"""Static guards for the problems a launch rehearsal on real Postgres found.

The test suite runs on SQLite, so it could not see that:
  * main.py's schema loader dropped 17 of 19 tables and produced two garbage
    statements, so bot 2.0 exited on startup;
  * five columns the code relies on existed only in the SQLite dev schema and
    in no Postgres migration, so lender permission checks and payments failed
    on the live database;
  * migration 001 indexed pre-rename loan_requests columns and failed against
    a database that never had the table.

These tests read the files and fail if any of that comes back.
scripts/rehearse_launch.py does the real thing against a restored backup.
"""

import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "scripts" / "migrations"


def _statements(path):
    from sqlscript import split_sql
    return split_sql(path.read_text(encoding="utf-8"))


class BotStartupSchemaTests(unittest.TestCase):

    def test_every_schema_table_reaches_the_loader(self):
        import main
        statements = main.load_schema()
        created = {t for s in statements
                   for t in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", s)}
        declared = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)",
                                  (ROOT / "schema.sql").read_text(encoding="utf-8")))
        self.assertEqual(declared - created, set(),
                         "tables in schema.sql that the bot's loader drops")

    def test_every_loaded_statement_is_sql(self):
        import main
        garbage = [s[:80] for s in main.load_schema()
                   if not re.match(r"\s*(CREATE|ALTER)\b", s, re.I)]
        self.assertEqual(garbage, [], "comment text leaking into statements")

    def test_init_database_succeeds_on_an_empty_database(self):
        import os
        import main
        path = str(Path(tempfile.mkdtemp()) / "startup.sqlite3")
        old = {k: os.environ.get(k) for k in ("DB_BACKEND", "SQLITE_DB_PATH")}
        os.environ["DB_BACKEND"], os.environ["SQLITE_DB_PATH"] = "sqlite", path
        try:
            self.assertTrue(main.init_database())
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        tables = {r[0] for r in sqlite3.connect(path).execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("user_roles", tables)
        self.assertIn("loan_requests", tables)


class PostgresColumnCoverageTests(unittest.TestCase):
    """Every column the dev schema adds after table creation needs a migration."""

    def _dev_added_columns(self):
        source = (ROOT / "local_db.py").read_text(encoding="utf-8")
        return re.findall(r'_ensure_column\(conn,\s*"(\w+)",\s*"(\w+)"', source)

    def _migration_columns(self):
        found = set()
        for path in sorted(MIGRATIONS.glob("*.sql")):
            for statement in _statements(path):
                flat = " ".join(statement.split())
                m = re.match(r"ALTER TABLE (\w+) (.*)", flat, re.I)
                if m:
                    for col in re.findall(r"ADD COLUMN IF NOT EXISTS (\w+)", m.group(2), re.I):
                        found.add((m.group(1).lower(), col.lower()))
                m = re.match(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*)\)$", flat, re.I)
                if m:
                    for col in re.findall(r"(?:^|, )(\w+) [A-Z]", m.group(2)):
                        found.add((m.group(1).lower(), col.lower()))
        return found

    def test_the_scan_sees_columns(self):
        self.assertGreater(len(self._dev_added_columns()), 20)

    def test_every_dev_column_has_a_postgres_migration(self):
        covered = self._migration_columns()
        missing = sorted(f"{t}.{c}" for t, c in self._dev_added_columns()
                         if (t, c) not in covered)
        self.assertEqual(missing, [], "columns only the SQLite dev schema creates: "
                                      + ", ".join(missing))


class MigrationSafetyTests(unittest.TestCase):

    def test_migration_001_uses_current_loan_request_columns(self):
        text = (MIGRATIONS / "001_dashboard_columns.sql").read_text(encoding="utf-8")
        for stale in ("loan_requests(status)", "loan_requests(borrower)"):
            self.assertNotIn(stale, text)

    def test_unique_indexes_cannot_abort_migration_013(self):
        """Old data may already hold duplicates; each index must be skippable."""
        text = (MIGRATIONS / "013_integrity_constraints.sql").read_text(encoding="utf-8")
        bare = re.findall(r"^CREATE UNIQUE INDEX", text, re.M)
        self.assertEqual(bare, [], "unguarded unique index in 013")
        self.assertEqual(text.count("EXCEPTION WHEN unique_violation"), 3)

    def test_every_migration_statement_is_idempotent(self):
        problems = []
        for path in sorted(MIGRATIONS.glob("*.sql")):
            for statement in _statements(path):
                flat = " ".join(statement.split())
                if flat.upper().startswith("DO "):
                    continue
                if re.match(r"(CREATE|ALTER)", flat, re.I) and "IF NOT EXISTS" not in flat.upper():
                    problems.append(f"{path.name}: {flat[:70]}")
                if flat.upper().startswith("ALTER") and (
                        len(re.findall(r"ADD COLUMN", flat, re.I))
                        != len(re.findall(r"ADD COLUMN IF NOT EXISTS", flat, re.I))):
                    problems.append(f"{path.name}: {flat[:70]}")
        self.assertEqual(problems, [])

    def test_no_migration_destroys_data(self):
        destructive = []
        for path in sorted(MIGRATIONS.glob("*.sql")):
            for statement in _statements(path):
                # A foreign key's "ON DELETE SET NULL" is not a data change.
                text = re.sub(r"\bON (DELETE|UPDATE)\b", "", statement, flags=re.I)
                if re.search(r"\b(DROP|DELETE|TRUNCATE|UPDATE)\b", text, re.I) \
                        and not statement.upper().lstrip().startswith("DO"):
                    destructive.append(f"{path.name}: {statement[:60]}")
        self.assertEqual(destructive, [])
