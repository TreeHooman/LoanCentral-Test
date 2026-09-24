"""scripts/rename_reddit_user.py moves records off a misspelled Reddit name."""

import importlib.util
from pathlib import Path

from tests.support.dbcase import RealDBTestCase

_spec = importlib.util.spec_from_file_location(
    "rename_reddit_user", Path(__file__).resolve().parents[1] / "scripts" / "rename_reddit_user.py")
rn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rn)


class RenameTests(RealDBTestCase):
    def setUp(self):
        super().setUp()
        for i, (lender, borrower) in enumerate((("Embarrassed-Throat42", "b1"), ("embarrassed-throat42", "b2"),
                                                ("l3", "embarrassed-throat42"), ("other", "b4"))):
            self.execute(
                "INSERT INTO loans (loan_id, lender, borrower, amount, amount_repaid, currency, status, "
                "date_created, original_thread) VALUES (%s, %s, %s, 10, 10, 'USD', 'repaid', CURRENT_TIMESTAMP, 'x')",
                (f"R{i}", lender, borrower))
        self.execute("INSERT INTO users (username, loans_as_borrower, loans_as_lender) VALUES (%s, 1, 2)",
                     ("embarrassed-throat42",))
        self.execute("INSERT INTO users (username, loans_as_borrower, loans_as_lender) VALUES (%s, 3, 4)",
                     ("embarassed-throat42",))

    def run_rename(self, apply):
        conn = self.connection()
        try:
            return rn.rename(conn, "embarrassed-throat42", "embarassed-throat42", apply=apply)
        finally:
            conn.close()

    def test_preview_changes_nothing(self):
        counts, _ = self.run_rename(apply=False)
        self.assertEqual(counts[("loans", "lender")], 2)
        self.assertEqual(counts[("loans", "borrower")], 1)
        self.assertEqual(len(self.execute("SELECT 1 FROM loans WHERE lower(lender) = 'embarrassed-throat42'")), 2)

    def test_apply_moves_the_records_and_merges_counts(self):
        self.run_rename(apply=True)
        self.assertEqual(self.execute("SELECT count(*) FROM loans WHERE lender = 'embarassed-throat42'")[0][0], 2)
        self.assertEqual(self.execute("SELECT count(*) FROM loans WHERE borrower = 'embarassed-throat42'")[0][0], 1)
        self.assertEqual(self.execute("SELECT count(*) FROM loans WHERE lower(lender) LIKE 'embarr%'")[0][0], 0)
        self.assertEqual(self.execute("SELECT loans_as_borrower, loans_as_lender FROM users "
                                      "WHERE username = 'embarassed-throat42'")[0], (4, 6))
        self.assertEqual(self.execute("SELECT count(*) FROM users WHERE username = 'embarrassed-throat42'")[0][0], 0)
        audit = self.execute("SELECT action_type FROM audit_logs WHERE target_id = 'embarassed-throat42'")
        self.assertIn(("reddit_username_renamed",), [tuple(a) for a in audit])

    def test_counts_toward_the_right_rank(self):
        import tiers
        self.run_rename(apply=True)
        self.assertEqual(tiers.repaid_counts("embarassed-throat42"), (2, 1))

    def test_refuses_to_rename_a_dashboard_account(self):
        self.make_user("embarrassed-throat42", role="lender")
        counts, message = self.run_rename(apply=True)
        self.assertIsNone(counts)
        self.assertIn("Link it instead", message)

    def test_rejects_non_reddit_names(self):
        with self.assertRaises(SystemExit):
            rn._clean("not a name!")
        self.assertEqual(rn._clean("u/Embarassed-Throat42"), "embarassed-throat42")
