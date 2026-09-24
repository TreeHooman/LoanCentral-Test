"""Dashboard updates reach Reddit within seconds (reddit_sync.drain_soon)."""

import os
import threading
import unittest
from unittest.mock import patch

import reddit_sync
import services
from tests.support.dbcase import RealDBTestCase

LOGIN = {"REDDIT_CLIENT_ID": "id", "REDDIT_CLIENT_SECRET": "s",
         "REDDIT_USERNAME": "loancentral", "REDDIT_PASSWORD": "p"}


class DrainSoonTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(reddit_sync, "SOON_DELAY", 0)
        patcher.start()
        self.addCleanup(patcher.stop)
        reddit_sync._soon_again.clear()

    def test_off_unless_switched_on(self):
        with patch.dict(os.environ, {**LOGIN, "REDDIT_SYNC_IN_DASHBOARD": ""}), \
             patch.object(reddit_sync, "run_once") as run:
            self.assertIsNone(reddit_sync.drain_soon())
        run.assert_not_called()

    def test_off_without_the_reddit_login(self):
        env = {**LOGIN, "REDDIT_SYNC_IN_DASHBOARD": "true", "REDDIT_PASSWORD": ""}
        with patch.dict(os.environ, env):
            self.assertFalse(reddit_sync.drain_soon_enabled())

    def test_runs_a_live_pass(self):
        with patch.dict(os.environ, {**LOGIN, "REDDIT_SYNC_IN_DASHBOARD": "true"}), \
             patch.object(reddit_sync, "run_once", return_value=({"considered": 0}, None)) as run:
            thread = reddit_sync.drain_soon()
            thread.join(5)
        run.assert_called_once_with(limit=25, live=True)

    def test_a_burst_of_updates_is_not_lost_or_doubled(self):
        """Updates queued while a pass runs are picked up by one more pass."""
        started, release = threading.Event(), threading.Event()
        calls = []

        def slow_pass(**kwargs):
            calls.append(1)
            if len(calls) == 1:
                started.set()
                release.wait(5)
            return {"considered": 0}, None

        with patch.dict(os.environ, {**LOGIN, "REDDIT_SYNC_IN_DASHBOARD": "true"}), \
             patch.object(reddit_sync, "run_once", side_effect=slow_pass):
            thread = reddit_sync.drain_soon()
            started.wait(5)
            self.assertIsNone(reddit_sync.drain_soon())   # joins the running pass
            self.assertIsNone(reddit_sync.drain_soon())
            release.set()
            thread.join(5)
        self.assertEqual(len(calls), 2)


class EnqueueHookTests(RealDBTestCase):
    def test_queueing_an_action_triggers_the_hook_after_commit(self):
        seen = []

        def hook():
            rows = self.execute("SELECT count(*) FROM reddit_actions")
            seen.append(rows[0][0])

        services.set_reddit_enqueue_hook(hook)
        self.addCleanup(services.set_reddit_enqueue_hook, reddit_sync.drain_soon)
        result, error = services.enqueue_reddit_action("lender_flair", target_user="x",
                                                       payload={"reddit_username": "x"})
        self.assertIsNone(error)
        self.assertEqual(seen, [1])          # the row was already committed

    def test_a_failing_hook_never_breaks_queueing(self):
        services.set_reddit_enqueue_hook(lambda: 1 / 0)
        self.addCleanup(services.set_reddit_enqueue_hook, reddit_sync.drain_soon)
        result, error = services.enqueue_reddit_action("lender_flair", target_user="y",
                                                       payload={"reddit_username": "y"})
        self.assertIsNone(error)
        self.assertTrue(result["ok"])

    def test_the_dashboard_installs_it(self):
        self.assertIs(services._reddit_enqueue_hook, reddit_sync.drain_soon)


if __name__ == "__main__":
    unittest.main()
