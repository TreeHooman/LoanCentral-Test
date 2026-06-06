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
    """Get database connection"""
    try:
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
    except Exception:
        logger.error("Database connection failed", exc_info=True)
        return None