"""
Keep the bot running: start main.py, and start it again whenever it stops.

    python scripts/run_bot_forever.py

Stop it with Ctrl+C (or close its window). To start it when you sign in to
Windows, see docs/LAUNCH_CHECKLIST.md step 6.

- Restarts after a crash or a reboot of the bot's own loop.
- Backs off when the bot keeps dying quickly (a settings mistake, Reddit
  down): 30 seconds, then doubling up to 15 minutes, so a broken setup does
  not hammer Reddit or fill the log. A run that lasted 10 minutes resets it.
- Only one copy per computer: a second one exits at once, so two bots can
  never answer the same post. (This does not see the OLD bot, which runs
  from its own folder; stop that one yourself.)
- Writes what it does to bot_supervisor.log next to main.py.
"""

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "bot_supervisor.lock"

FIRST_DELAY = 30          # seconds before the first restart
MAX_DELAY = 15 * 60       # never wait longer than this
STABLE_RUN = 10 * 60      # a run this long counts as healthy and resets the delay

log = logging.getLogger("bot_supervisor")


def next_delay(previous_delay, ran_for):
    """Seconds to wait before restarting a bot that ran for `ran_for` seconds."""
    if ran_for >= STABLE_RUN or previous_delay is None:
        return FIRST_DELAY
    return min(previous_delay * 2, MAX_DELAY)


def single_instance_lock():
    """Hold an exclusive lock on LOCK_PATH for the life of the process, or exit."""
    handle = open(LOCK_PATH, "a+")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise SystemExit("The bot is already running on this computer (bot_supervisor.lock is held). "
                         "Close that window first.")
    return handle  # keep a reference: closing it releases the lock


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s supervisor %(message)s",
        handlers=[logging.FileHandler(ROOT / "bot_supervisor.log", encoding="utf-8"),
                  logging.StreamHandler()],
    )
    lock = single_instance_lock()  # noqa: F841  (held until exit)

    delay = None
    while True:
        started = time.monotonic()
        log.info("starting the bot")
        try:
            code = subprocess.call([sys.executable, str(ROOT / "main.py")], cwd=str(ROOT))
        except KeyboardInterrupt:
            log.info("stopped by Ctrl+C")
            return 0
        ran_for = time.monotonic() - started
        delay = next_delay(delay, ran_for)
        log.warning("the bot stopped (exit code %s) after %d s; restarting in %d s",
                    code, ran_for, delay)
        try:
            time.sleep(delay)
        except KeyboardInterrupt:
            log.info("stopped by Ctrl+C")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
