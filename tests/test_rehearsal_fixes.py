"""Bugs found by running the site and bot against the real June data on Postgres.

SQLite accepted all three, which is why the rest of the suite missed them;
these tests pin the behaviour and the SQL shapes that Postgres needs.
"""

import inspect
import time
from decimal import Decimal
from pathlib import Path

import offers
import services
from tests.support.dbcase import RealDBTestCase

ROOT = Path(__file__).resolve().parents[1]


class ConfirmStoresThePublicLoanIdTests(RealDBTestCase):
    """`$confirm` saved the loan, then crashed storing the 13-digit public loan
    ID in an INTEGER column, so the borrower never got a reply."""

    def test_confirm_records_the_loans_public_id_on_the_offer(self):
        offer, error = offers.create_offer("lenderx", "borrowery", Decimal("50"), "USD",
                                           "https://reddit.com/r/loancentral/comments/o1/x/")
        self.assertIsNone(error)
        loan_id, _, error = offers.confirm_offer(offer["id"], "borrowery")
        self.assertIsNone(error)
        stored = self.execute("SELECT loan_db_id, status FROM loan_offers WHERE id = %s", (offer["id"],))[0]
        self.assertEqual(str(stored[0]), str(loan_id))
        self.assertEqual(stored[1], "confirmed")
        self.assertEqual(len(self.execute("SELECT 1 FROM loans WHERE loan_id = %s", (loan_id,))), 1)

    def test_the_column_is_text_everywhere(self):
        migration = (ROOT / "scripts" / "migrations" / "020_loan_offer_loan_id_text.sql").read_text()
        self.assertIn("ALTER COLUMN loan_db_id TYPE TEXT", migration)
        schema = (ROOT / "schema.sql").read_text()
        self.assertRegex(schema, r"loan_db_id TEXT")

    def test_create_loan_returns_the_public_id(self):
        loan_id, error = services.create_loan("lendera", "borrowerb", Decimal("10"), "USD", "https://x")
        self.assertIsNone(error)
        self.assertIsInstance(loan_id, str)
        self.assertTrue(loan_id.isdigit() and len(loan_id) > 10)


class TimelineOnPostgresTests(RealDBTestCase):
    """The admin user timeline mixed a JSON column with '' in COALESCE, which
    Postgres rejects (500 on /api/audit/user/<name>/timeline)."""

    def test_json_columns_are_cast_to_text(self):
        sql = inspect.getsource(services.get_user_activity_timeline)
        self.assertIn("COALESCE(CAST(new_value_json AS TEXT), '')", sql)
        self.assertIn("COALESCE(CAST(details AS TEXT), '')", sql)
        self.assertNotIn("COALESCE(new_value_json, '')", sql)

    def test_timeline_includes_audit_entries_with_json_values(self):
        services.log_audit("mod1", "mod", "note_added", "user", "someone", new_value={"note": "hi"})
        events, error = services.get_user_activity_timeline("someone")
        self.assertIsNone(error)
        self.assertEqual(events[0]["event_type"], "note_added")
        self.assertIn("hi", events[0]["detail"])


class CooldownOnlyStopsDoublePostsTests(RealDBTestCase):
    """The 15-second cooldown was per person per command, so a second
    `$paid_with_id` for a different loan was silently dropped."""

    def setUp(self):
        super().setUp()
        import main
        self.manager = main.command_manager
        self.manager.recent_commands.clear()
        self.manager.user_command_times.clear()
        self.addCleanup(self.manager.recent_commands.clear)
        self.addCleanup(self.manager.user_command_times.clear)

    def test_different_commands_both_go_through(self):
        self.assertFalse(self.manager._is_rate_limited("lender", "$paid_with_id", "$paid_with_id 111 20 usd"))
        self.assertFalse(self.manager._is_rate_limited("lender", "$paid_with_id", "$paid_with_id 222 30 usd"))

    def test_the_same_command_again_is_a_double_post(self):
        self.assertFalse(self.manager._is_rate_limited("lender", "$paid_with_id", "$paid_with_id 111 20 usd"))
        self.assertTrue(self.manager._is_rate_limited("Lender", "$paid_with_id", "$paid_with_id  111 20 USD"))

    def test_one_person_flooding_different_commands_is_capped(self):
        cap = self.manager.per_user_per_minute
        results = [self.manager._is_rate_limited("spammer", "$stats", f"$stats u/user{i}")
                   for i in range(cap + 5)]
        self.assertEqual(results[:cap], [False] * cap)
        self.assertTrue(all(results[cap:]))
        # Someone else is unaffected.
        self.assertFalse(self.manager._is_rate_limited("lender", "$stats", "$stats u/x"))

    def test_it_expires(self):
        self.manager._is_rate_limited("lender", "$fund", "$fund req-1")
        key = next(iter(self.manager.recent_commands))
        self.manager.recent_commands[key] = time.time() - self.manager.cooldown_seconds - 1
        self.assertFalse(self.manager._is_rate_limited("lender", "$fund", "$fund req-1"))
