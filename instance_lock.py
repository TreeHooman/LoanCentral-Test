"""One copy per computer: an exclusive, non-blocking lock on a file.

Used by the supervisor (scripts/run_bot_forever.py) and by the bot itself
(main.py). The bot holds its own lock so that a bot left running after its
supervisor was killed can never be joined by a second one answering the same
comments.

The lock is released when the process exits, however it exits.
"""

import os


def acquire(path, message):
    """Hold an exclusive lock on `path` for the life of the process, or exit
    with `message`. Returns the open handle; keep a reference to it."""
    handle = open(path, "a+")
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
        raise SystemExit(message)
    return handle


def is_held(path):
    """True if another process holds the lock on `path` right now."""
    try:
        handle = acquire(path, "")
    except SystemExit:
        return True
    handle.close()
    return False
