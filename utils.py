import praw
import psycopg2
import logging
import os
import time
import threading
from dotenv import load_dotenv
from prawcore.requestor import Requestor

# Load environment variables
load_dotenv()

logger = logging.getLogger("LoanCentral")

# ---------------------------------------------------------------------------
# Reddit API rate limiter
# Reddit's free tier allows 100 OAuth requests/min (averaged over a 10-min
# window). We hard-cap at 80/min to stay safely under.
#
# Enforcement is at the transport level: _ThrottledRequestor gates EVERY
# outgoing HTTP request PRAW makes (stream polls, lazy loads, replies, DMs,
# flair reads, token refreshes), so no call site can bypass the cap.
# Explicit reddit_limiter.wait() calls sprinkled in bot code are now
# redundant but harmless (each one just consumes a slot).
# ---------------------------------------------------------------------------

class _RedditRateLimiter:
    """Sliding-window cap on outgoing Reddit requests.

    Two layers:
      1. A local 80/min sliding window — conservative against the documented
         100 QPM free-tier limit.
      2. Reddit's own accounting, read back from the X-Ratelimit-* response
         headers. Reddit averages over a ~10 minute window, so the local
         per-minute count alone can drift out of step with the server's view;
         when the server says the budget is nearly gone we hold off until its
         reset instead of trusting the local count.
    """

    def __init__(self, calls_per_minute: int = 80):
        self._limit = calls_per_minute
        self._lock  = threading.Lock()
        self._times: list = []  # timestamps of recent calls
        # Monotonic deadline to stay quiet until, set from server headers.
        self._hold_until = 0.0
        self._last_remaining = None

    def wait(self):
        with self._lock:
            now = time.monotonic()

            # 1. Respect an explicit server-signalled exhaustion window.
            if self._hold_until > now:
                pause = self._hold_until - now
                logger.warning(
                    f"Reddit rate limit: server reports budget exhausted, "
                    f"holding {pause:.1f}s until reset"
                )
                time.sleep(pause)
                now = time.monotonic()

            # 2. Local sliding window.
            self._times = [t for t in self._times if now - t < 60]
            if len(self._times) >= self._limit:
                oldest  = self._times[0]
                wait_s  = 60.0 - (now - oldest) + 0.05
                logger.warning(f"Reddit rate limit guard: sleeping {wait_s:.1f}s (hit {self._limit}/min cap)")
                time.sleep(wait_s)
                now = time.monotonic()
                self._times = [t for t in self._times if now - t < 60]
            self._times.append(now)

    def note_response(self, response):
        """Feed Reddit's own budget accounting back into the limiter."""
        headers = getattr(response, "headers", None)
        if not headers:
            return
        try:
            remaining = headers.get("x-ratelimit-remaining")
            reset     = headers.get("x-ratelimit-reset")
            if remaining is None or reset is None:
                return
            remaining = float(remaining)
            reset     = float(reset)
        except (TypeError, ValueError):
            return

        self._last_remaining = remaining
        # Keep a small reserve so a burst can never land us on exactly zero.
        if remaining <= 5 and reset > 0:
            with self._lock:
                self._hold_until = max(self._hold_until, time.monotonic() + reset)
            logger.warning(
                f"Reddit rate limit: {remaining:.0f} requests left in the server "
                f"window, pausing {reset:.0f}s"
            )

    @property
    def last_remaining(self):
        """Requests Reddit says are left in the current window (None if unknown)."""
        return self._last_remaining


reddit_limiter = _RedditRateLimiter()


class _ThrottledRequestor(Requestor):
    """Gates every outgoing Reddit HTTP request through reddit_limiter."""

    def request(self, *args, **kwargs):
        reddit_limiter.wait()
        response = super().request(*args, **kwargs)
        reddit_limiter.note_response(response)
        return response


BOT_VERSION = "1.0"

# Reddit asks for a unique, self-identifying User-Agent in the documented shape
#   <platform>:<app ID>:<version string> (by /u/<reddit username>)
# A generic, shared, or placeholder UA is one of the documented ways to get
# throttled or blocked, so refuse to ship the sample value.
_UA_PLACEHOLDERS = ("your_username", "yourusername", "your-username",
                    "changeme", "example", "<", ">")


def user_agent_problems(user_agent: str, username: str):
    """Return a list of reasons this User-Agent is not acceptable to Reddit."""
    problems = []
    ua = (user_agent or "").strip()
    if not ua:
        problems.append("REDDIT_USER_AGENT is not set.")
        return problems
    low = ua.lower()
    for marker in _UA_PLACEHOLDERS:
        if marker in low:
            problems.append(
                f"REDDIT_USER_AGENT still contains the placeholder {marker!r} "
                f"({ua!r}). Reddit requires a real identifying user agent."
            )
            break
    if username and f"/u/{username.lower()}" not in low and f"by {username.lower()}" not in low:
        problems.append(
            f"REDDIT_USER_AGENT should identify the account running the bot, "
            f"e.g. 'python:loancentral-bot:{BOT_VERSION} (by /u/{username})'."
        )
    return problems


def _resolve_user_agent():
    ua       = (os.getenv("REDDIT_USER_AGENT") or "").strip()
    username = (os.getenv("REDDIT_USERNAME") or "").strip()
    if not user_agent_problems(ua, username):
        return ua
    if username:
        generated = f"python:loancentral-bot:{BOT_VERSION} (by /u/{username})"
        logger.warning(
            f"REDDIT_USER_AGENT was missing or a placeholder; using {generated!r}. "
            "Set REDDIT_USER_AGENT explicitly to silence this."
        )
        return generated
    logger.error(
        "REDDIT_USER_AGENT is unusable and REDDIT_USERNAME is unset — cannot build "
        "a compliant user agent. Reddit may throttle or block this client."
    )
    return ua or f"python:loancentral-bot:{BOT_VERSION}"


def reddit_config_problems():
    """Blocking problems that must be fixed before talking to the live API."""
    problems = []
    required = {
        "REDDIT_CLIENT_ID":     os.getenv("REDDIT_CLIENT_ID"),
        "REDDIT_CLIENT_SECRET": os.getenv("REDDIT_CLIENT_SECRET"),
        "REDDIT_USERNAME":      os.getenv("REDDIT_USERNAME"),
        "REDDIT_PASSWORD":      os.getenv("REDDIT_PASSWORD"),
    }
    for name, value in required.items():
        if not (value or "").strip():
            problems.append(f"{name} is not set.")
    if not (os.getenv("SUBREDDITS") or os.getenv("SUBREDDIT") or "").strip():
        problems.append("Neither SUBREDDITS nor SUBREDDIT is set — nothing to monitor.")
    problems.extend(user_agent_problems(
        os.getenv("REDDIT_USER_AGENT"), os.getenv("REDDIT_USERNAME") or ""))
    # Every bot reply links to the dashboard. Unset, bot_messages falls back to
    # a default address, and every link in every comment would be wrong.
    dashboard_url = (os.getenv("DASHBOARD_URL") or "").strip()
    if not dashboard_url:
        problems.append("DASHBOARD_URL is not set — bot replies link to the dashboard "
                        "(e.g. https://loancentral.net).")
    elif not dashboard_url.startswith("https://"):
        problems.append(f"DASHBOARD_URL must be an https:// address ({dashboard_url!r}).")
    return problems


# Reddit client. REDDIT_MODE=dry_run swaps the live PRAW client for a local
# stub that logs outbound actions instead of calling Reddit (see
# dry_run_reddit.py). DB and command logic are unaffected. Defaults to live.
_reddit_mode = (os.getenv("REDDIT_MODE") or "live").strip().lower()
if _reddit_mode in ("dry_run", "dry-run", "dryrun", "off"):
    from dry_run_reddit import DryRunReddit
    reddit = DryRunReddit()
    logger.warning(f"REDDIT_MODE={_reddit_mode}: using DryRunReddit stub - no Reddit API calls will be made")
else:
    reddit = praw.Reddit(
        client_id=os.getenv("REDDIT_CLIENT_ID"),
        client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
        username=os.getenv("REDDIT_USERNAME"),
        password=os.getenv("REDDIT_PASSWORD"),
        user_agent=_resolve_user_agent(),
        requestor_class=_ThrottledRequestor,
        # When Reddit answers a write with "doing that too much, try again in N
        # minutes", sleep up to 5 min and retry instead of raising and losing the
        # reply (default is only 5 seconds).
        ratelimit_seconds=300,
    )

_LOCAL_DB_HOSTS = ("localhost", "127.0.0.1", "::1", "")


def db_ssl_mode(host):
    """SSL is required for every database that is not on this machine.

    This used to require it only for a list of known providers and "prefer" it
    elsewhere. Neon (*.neon.tech) was not on the list, and "prefer" quietly
    falls back to an unencrypted connection, database password included.
    """
    return "prefer" if (host or "").strip().lower() in _LOCAL_DB_HOSTS else "require"


# PostgreSQL connection
def get_db_connection():
    """Get database connection"""
    if os.getenv("DB_BACKEND", "").lower() == "sqlite":
        from local_db import get_sqlite_connection
        return get_sqlite_connection()

    try:
        database_url = os.getenv("DATABASE_URL", "").strip()
        if database_url:
            return psycopg2.connect(database_url, sslmode="require")

        host = os.getenv("DB_HOST", "localhost")
        ssl_mode = db_ssl_mode(host)
        
        return psycopg2.connect(
            host=host,
            port=os.getenv("DB_PORT"),
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            sslmode=ssl_mode
        )
    except Exception as e:
        logger.error(f"PostgreSQL connection failed: {e}", exc_info=True)
        print(f"[DB ERROR] PostgreSQL connection failed: {e}")
        print(f"[DB ERROR] host={os.getenv('DB_HOST')} port={os.getenv('DB_PORT')} db={os.getenv('DB_NAME')} user={os.getenv('DB_USER')}")
        if os.getenv("LOANCENTRAL_ENV", "prod") != "prod":
            print("[DB FALLBACK] Falling back to local SQLite database.")
            from local_db import get_sqlite_connection
            return get_sqlite_connection()
        return None
