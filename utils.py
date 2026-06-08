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
    """Get database connection. Supports DATABASE_URL (Render/Heroku) or individual vars."""
    try:
        database_url = os.getenv("DATABASE_URL", "")
        if database_url:
            # Render provides postgres:// but psycopg2 needs postgresql://
            if database_url.startswith("postgres://"):
                database_url = database_url.replace("postgres://", "postgresql://", 1)
            return psycopg2.connect(database_url, sslmode="require")

        host = os.getenv("DB_HOST", "localhost")
        ssl_mode = "require" if any(x in host for x in ("render.com", "amazonaws.com", "heroku.com")) else "prefer"
        return psycopg2.connect(
            host=host,
            port=os.getenv("DB_PORT"),
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            sslmode=ssl_mode,
        )
    except Exception:
        logger.error("Database connection failed", exc_info=True)
        return None