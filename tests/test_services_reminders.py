"""
Tests for send_due_reminders() and get_borrower_stats() in services.
"""
import sys
import os
import unittest
from decimal import Decimal
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services
from tests.support.fakes import FakeDb, fake_utils_module


class SendDueRemindersTests(unittest.TestCase):
    def _run_send_due_reminders(self, fake_db, sms_calls=None):
        captured = sms_calls if sms_calls is not None else []
        with patch.dict(sys.modules, {"utils": fake_utils_module(fake_db)}):
            with patch("notifications.send_sms", side_effect=lambda t, m: captured.append((t, m))):
                count, error = services.send_due_reminders()
        return count, error, captured

    def test_db_failure_returns_error(self):
        with patch.object(services, "_get_db", return_value=None):
            count, error = services.send_due_reminders()
        self.assertEqual(count, 0)
        self.assertIsNotNone(error)

    def test_no_due_loans_returns_zero(self):
        fake_db = FakeDb()
        count, error, sms = self._run_send_due_reminders(fake_db)
        # FakeCursor returns [] for the JOIN query, so count should be 0
        self.assertEqual(count, 0)
        self.assertIsNone(error)
        self.assertEqual(len(sms), 0)


class GetBorrowerStatsTests(unittest.TestCase):
    def _run(self, fake_db, borrower="borrower"):
        with patch.dict(sys.modules, {"utils": fake_utils_module(fake_db)}):
            return services.get_borrower_stats(borrower)

    def test_returns_dict_with_required_keys(self):
        fake_db = FakeDb()
        stats, error = self._run(fake_db)
        self.assertIsNone(error)
        required = {"total_loans", "active_loans", "unpaid_loans", "repaid_loans",
                    "total_borrowed", "total_repaid", "outstanding", "overdue_loans"}
        self.assertTrue(required.issubset(set(stats.keys())))

    def test_db_failure_returns_error(self):
        with patch.object(services, "_get_db", return_value=None):
            stats, error = services.get_borrower_stats("borrower")
        self.assertIsNone(stats)
        self.assertIsNotNone(error)


if __name__ == "__main__":
    unittest.main()
