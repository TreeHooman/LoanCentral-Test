import praw
import psycopg2
import logging
import os
import time
import threading
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger("LoanCentral")

# ---------------------------------------------------------------------------
# Reddit API rate limiter
# Reddit allows ~100 OAuth requests/min. We cap at 80 to stay safely under.
# Call reddit_limiter.wait() before any outgoing Reddit API write (reply, send).
# PRAW stream reads are throttled automatically by PRAW itself.
# ---------------------------------------------------------------------------

class _RedditRateLimiter:
    def __init__(self, calls_per_minute: int = 80):
        self._limit = calls_per_minute
        self._lock  = threading.Lock()
        self._times: list = []  # timestamps of recent calls

    def wait(self):
        with self._lock:
            now = time.monotonic()
            # Drop timestamps older than 60 s
            self._times = [t for t in self._times if now - t < 60]
            if len(self._times) >= self._limit:
                oldest  = self._times[0]
                wait_s  = 60.0 - (now - oldest) + 0.05
                logger.warning(f"Reddit rate limit guard: sleeping {wait_s:.1f}s (hit {self._limit}/min cap)")
                time.sleep(wait_s)
                now = time.monotonic()
                self._times = [t for t in self._times if now - t < 60]
            self._times.append(now)

reddit_limiter = _RedditRateLimiter()

# Reddit API credentials
reddit = praw.Reddit(
    client_id=os.getenv("REDDIT_CLIENT_ID"),
    client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
    username=os.getenv("REDDIT_USERNAME"),
    password=os.getenv("REDDIT_PASSWORD"),
    user_agent=os.getenv("REDDIT_USER_AGENT")
)

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

        # Determine SSL mode based on host
        host = os.getenv("DB_HOST", "localhost")
        ssl_mode = "require" if "render.com" in host or "amazonaws.com" in host or "heroku.com" in host else "prefer"
        
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
