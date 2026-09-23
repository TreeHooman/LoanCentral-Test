"""/ping must not touch the database; analytics pruning keeps the window."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import services
from tests.support.dbcase import RealDBTestCase


def _stamp(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")


class PingTests(RealDBTestCase):
    def test_ping_answers_without_opening_a_connection(self):
        with patch.object(services, "_get_db", side_effect=AssertionError("DB opened")):
            response = self.client.get("/ping")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")

    def test_ping_skips_the_ban_lookup_for_a_signed_in_user(self):
        with self.client.session_transaction() as sess:
            sess["username"] = "somebody"
            sess["role"] = "lender"
        with patch.object(services, "is_user_banned", side_effect=AssertionError("DB opened")):
            response = self.client.get("/ping")
        self.assertEqual(response.status_code, 200)


class PruneAnalyticsTests(RealDBTestCase):
    def setUp(self):
        super().setUp()
        services.log_analytics_event("warm", "page_view")  # builds the schema
        self.execute("DELETE FROM analytics_events")
        for username, days_ago in (("old", 120), ("edge", 91), ("recent", 10), ("today", 0)):
            self.execute(
                "INSERT INTO analytics_events (username, event_type, created_at) VALUES (%s, %s, %s)",
                (username, "page_view", _stamp(days_ago)),
            )

    def remaining(self):
        return sorted(r[0] for r in self.query("SELECT username FROM analytics_events"))

    def test_deletes_only_rows_older_than_the_window(self):
        deleted, error = services.prune_analytics_events(90)
        self.assertIsNone(error)
        self.assertEqual(deleted, 2)
        self.assertEqual(self.remaining(), ["recent", "today"])

    def test_default_window_is_ninety_days(self):
        self.assertEqual(services.ANALYTICS_RETENTION_DAYS, 90)
        services.prune_analytics_events()
        self.assertEqual(self.remaining(), ["recent", "today"])

    def test_refuses_a_window_that_would_wipe_everything(self):
        deleted, error = services.prune_analytics_events(0)
        self.assertEqual(deleted, 0)
        self.assertIsNotNone(error)
        self.assertEqual(len(self.remaining()), 4)
