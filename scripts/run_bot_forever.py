"""
Keep the bot running: start main.py, and start it again whenever it stops or
freezes.

    python scripts/run_bot_forever.py            # run it (Ctrl+C to stop)
    python scripts/run_bot_forever.py --status   # is it running and healthy?
    python scripts/run_bot_forever.py --stop     # stop it, and keep it stopped
    python scripts/run_bot_forever.py --start    # allow it to run again, and run it

To have Windows start it by itself (at sign-in, and again within 5 minutes if
it is ever closed), run scripts/install_bot_task.ps1 once. See
docs/LAUNCH_CHECKLIST.md step 6.

- Restarts after a crash.
- Restarts a frozen bot: main.py writes bot_heartbeat.txt every minute while
  its Reddit streams are answering; if that goes quiet for HANG_AFTER, the bot
  is stopped and started again. (A crash-only supervisor misses a bot whose
  connection hangs: the process stays alive and answers nothing.)
- Backs off when the bot keeps dying quickly (a settings mistake, Reddit
  down): 30 seconds, then doubling up to 15 minutes, so a broken setup does
  not hammer Reddit or fill the log. A run that lasted 10 minutes resets it.
- Only one copy per computer: a second one exits at once, so two bots can
  never answer the same post. main.py holds its own lock too, so a bot left
  running after its supervisor was killed is never joined by a second one.
  (This does not see the OLD bot, which runs from its own folder; stop that
  one yourself.)
- --stop leaves a bot_supervisor.stop file; while it exists the supervisor
  will not start, so the scheduled task cannot bring the bot back. --start
  removes it.
- Writes what it does to bot_supervisor.log next to main.py.
"""

import argparse
import logging
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import instance_lock  # noqa: E402

LOCK_PATH = ROOT / "bot_supervisor.lock"
STOP_PATH = ROOT / "bot_supervisor.stop"
HEARTBEAT_PATH = ROOT / "bot_heartbeat.txt"

FIRST_DELAY = 30          # seconds before the first restart
MAX_DELAY = 15 * 60       # never wait longer than this
STABLE_RUN = 10 * 60      # a run this long counts as healthy and resets the delay
HANG_AFTER = 15 * 60      # no heartbeat for this long = frozen; restart it
CHECK_EVERY = 5           # seconds between checks on the running bot

log = logging.getLogger("bot_supervisor")


def next_delay(previous_delay, ran_for):
    """Seconds to wait before restarting a bot that ran for `ran_for` seconds."""
    if ran_for >= STABLE_RUN or previous_delay is None:
        return FIRST_DELAY
    return min(previous_delay * 2, MAX_DELAY)


def single_instance_lock():
    """Hold an exclusive lock on LOCK_PATH for the life of the process, or exit."""
    return instance_lock.acquire(
        LOCK_PATH, "The bot is already running on this computer (bot_supervisor.lock is held). "
                   "Close that window first.")


def heartbeat_age(started_at, now=None):
    """Seconds since the bot last showed it was working, counting from its start
    (wall-clock time, like the heartbeat file's timestamp)."""
    now = time.time() if now is None else now
    try:
        last = max(float(HEARTBEAT_PATH.read_text().strip() or 0), started_at)
    except (OSError, ValueError):
        last = started_at
    return now - last


def stop_requested():
    return STOP_PATH.exists()


def _stop_bot(proc):
    proc.terminate()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def run_bot_once():
    """Run main.py until it exits, freezes, or a stop is requested.
    Returns (reason, exit code)."""
    started_at = time.time()
    proc = subprocess.Popen([sys.executable, str(ROOT / "main.py")], cwd=str(ROOT))
    try:
        while proc.poll() is None:
            time.sleep(CHECK_EVERY)
            if stop_requested():
                log.info("stop requested; stopping the bot")
                _stop_bot(proc)
                return "stopped", proc.returncode
            age = heartbeat_age(started_at)
            if age > HANG_AFTER:
                log.warning("no heartbeat for %d s: the bot looks frozen; restarting it", age)
                _stop_bot(proc)
                return "frozen", proc.returncode
    except KeyboardInterrupt:
        _stop_bot(proc)
        raise
    return "exited", proc.returncode


def status():
    running = instance_lock.is_held(LOCK_PATH)
    print("Supervisor: " + ("running" if running else "NOT running"))
    try:
        age = time.time() - float(HEARTBEAT_PATH.read_text().strip())
        state = ("healthy" if age < 5 * 60 else "QUIET") if running else "not running"
        print(f"Bot heartbeat: {age / 60:.1f} min ago ({state})")
    except (OSError, ValueError):
        print("Bot heartbeat: none yet")
    if stop_requested():
        print("Stopped on purpose (bot_supervisor.stop exists). Start again with --start.")
    return 0 if running else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Keep the LoanCentral bot running.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_true", help="show whether the bot is running")
    group.add_argument("--stop", action="store_true", help="stop the bot and keep it stopped")
    group.add_argument("--start", action="store_true", help="allow the bot to run again, and run it")
    args = parser.parse_args(argv)

    if args.status:
        return status()
    if args.stop:
        STOP_PATH.write_text("Remove this file (or run run_bot_forever.py --start) to let the bot run.\n")
        print("Stop requested. The bot stops within a few seconds and stays stopped "
              "until you run: python scripts/run_bot_forever.py --start")
        return 0
    if args.start:
        STOP_PATH.unlink(missing_ok=True)
    elif stop_requested():
        # The scheduled task launches this every few minutes; stay down.
        return 0

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s supervisor %(message)s",
        # No console under pythonw (the scheduled task): log to the file only.
        handlers=[logging.FileHandler(ROOT / "bot_supervisor.log", encoding="utf-8")]
                 + ([logging.StreamHandler()] if sys.stderr else []),
    )
    lock = single_instance_lock()  # noqa: F841  (held until exit)

    delay = None
    while True:
        started = time.monotonic()
        log.info("starting the bot")
        try:
            reason, code = run_bot_once()
        except KeyboardInterrupt:
            log.info("stopped by Ctrl+C")
            return 0
        if reason == "stopped":
            return 0
        ran_for = time.monotonic() - started
        delay = next_delay(delay, ran_for)
        log.warning("the bot %s (exit code %s) after %d s; restarting in %d s",
                    "froze" if reason == "frozen" else "stopped", code, ran_for, delay)
        waited = 0
        try:
            while waited < delay:
                if stop_requested():
                    log.info("stop requested; not restarting")
                    return 0
                time.sleep(1)
                waited += 1
        except KeyboardInterrupt:
            log.info("stopped by Ctrl+C")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
