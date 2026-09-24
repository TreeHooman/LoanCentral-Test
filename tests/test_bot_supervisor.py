"""The supervisor restarts the bot, backing off when it keeps crashing."""

import importlib.util
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "run_bot_forever", Path(__file__).resolve().parents[1] / "scripts" / "run_bot_forever.py")
sup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sup)


class BackoffTests(unittest.TestCase):
    def test_first_restart_waits_the_short_delay(self):
        self.assertEqual(sup.next_delay(None, 5), sup.FIRST_DELAY)

    def test_quick_crashes_double_the_wait_up_to_the_cap(self):
        delay, seen = None, []
        for _ in range(10):
            delay = sup.next_delay(delay, 3)
            seen.append(delay)
        self.assertEqual(seen[:4], [30, 60, 120, 240])
        self.assertEqual(max(seen), sup.MAX_DELAY)

    def test_a_healthy_run_resets_the_wait(self):
        self.assertEqual(sup.next_delay(sup.MAX_DELAY, sup.STABLE_RUN), sup.FIRST_DELAY)


class SingleInstanceTests(unittest.TestCase):
    def test_a_second_copy_refuses_to_start(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(sup, "LOCK_PATH", Path(tmp) / "bot.lock"):
            first = sup.single_instance_lock()
            try:
                with self.assertRaises(SystemExit):
                    sup.single_instance_lock()
            finally:
                first.close()
            sup.single_instance_lock().close()  # free again once the first exits
