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


class FreezeAndStopTests(unittest.TestCase):
    """A frozen bot is restarted; --stop keeps it down; --status reports."""

    def setUp(self):
        import tempfile
        from unittest.mock import patch
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        for name, value in (("LOCK_PATH", self.dir / "sup.lock"), ("STOP_PATH", self.dir / "sup.stop"),
                            ("HEARTBEAT_PATH", self.dir / "hb.txt"), ("ROOT", self.dir),
                            ("CHECK_EVERY", 0.05)):
            p = patch.object(sup, name, value)
            p.start()
            self.addCleanup(p.stop)

    def fake_bot(self, body):
        (self.dir / "main.py").write_text(body)

    def test_heartbeat_age_counts_from_start_until_the_first_beat(self):
        self.assertAlmostEqual(sup.heartbeat_age(1000, now=1100), 100)
        sup.HEARTBEAT_PATH.write_text("1090")
        self.assertAlmostEqual(sup.heartbeat_age(1000, now=1100), 10)
        sup.HEARTBEAT_PATH.write_text("900")      # left over from an earlier run
        self.assertAlmostEqual(sup.heartbeat_age(1000, now=1100), 100)

    def test_a_frozen_bot_is_stopped(self):
        from unittest.mock import patch
        self.fake_bot("import time\ntime.sleep(60)\n")          # alive, never beats
        with patch.object(sup, "HANG_AFTER", 0.5):
            reason, _ = sup.run_bot_once()
        self.assertEqual(reason, "frozen")

    def test_a_bot_that_beats_is_left_alone(self):
        from unittest.mock import patch
        hb = str(sup.HEARTBEAT_PATH).replace("\\", "/")
        self.fake_bot("import time\nfor _ in range(15):\n"
                      f"    open(r'{hb}', 'w').write(str(int(time.time())))\n"
                      "    time.sleep(0.1)\n")
        # Generous limit: starting Python alone can take seconds on a busy machine.
        with patch.object(sup, "HANG_AFTER", 10):
            reason, code = sup.run_bot_once()
        self.assertEqual((reason, code), ("exited", 0))

    def test_stop_request_stops_the_running_bot(self):
        import threading
        self.fake_bot("import time\ntime.sleep(60)\n")
        threading.Timer(0.3, lambda: sup.STOP_PATH.write_text("stop")).start()
        reason, _ = sup.run_bot_once()
        self.assertEqual(reason, "stopped")

    def test_stopped_means_the_scheduled_task_cannot_start_it(self):
        from unittest.mock import patch
        self.assertEqual(sup.main(["--stop"]), 0)
        self.assertTrue(sup.STOP_PATH.exists())
        with patch.object(sup, "run_bot_once", side_effect=AssertionError("started")):
            self.assertEqual(sup.main([]), 0)

    def test_start_clears_the_stop(self):
        from unittest.mock import patch
        sup.STOP_PATH.write_text("stop")
        with patch.object(sup, "run_bot_once", return_value=("stopped", 0)):
            self.assertEqual(sup.main(["--start"]), 0)
        self.assertFalse(sup.STOP_PATH.exists())

    def test_status(self):
        import io
        from contextlib import redirect_stdout
        out = io.StringIO()
        with redirect_stdout(out):
            code = sup.status()
        self.assertEqual(code, 1)
        self.assertIn("NOT running", out.getvalue())
        held = sup.single_instance_lock()
        try:
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(sup.status(), 0)
        finally:
            held.close()


class BotHealthTests(unittest.TestCase):
    def test_streams_are_healthy_only_while_both_are_heard_from(self):
        import main
        now = 10_000
        main._stream_seen.update(comments=now - 5, posts=now - 5)
        self.assertTrue(main.streams_healthy(now))
        main._stream_seen["posts"] = now - main.STREAM_QUIET_AFTER - 1
        self.assertFalse(main.streams_healthy(now))
