import praw
import psycopg2
import logging
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger("LoanCentral")

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
    """Get database connection.

    Prefers DATABASE_URL when set (Render/Heroku style).  psycopg2 requires
    the scheme to be 'postgresql://' rather than 'postgres://', so the prefix
    is normalised before connecting.  Falls back to individual DB_* variables
    when DATABASE_URL is not present.
    """
    try:
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            # Render (and some other providers) emit 'postgres://' but psycopg2
            # only accepts 'postgresql://'.
            if database_url.startswith("postgres://"):
                database_url = "postgresql://" + database_url[len("postgres://"):]
            return psycopg2.connect(database_url, sslmode="require")

        # Fall back to individual connection parameters
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
    except Exception:
        logger.error("Database connection failed", exc_info=True)
        return None