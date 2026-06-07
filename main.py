import logging
import os
import threading
import sys
import time
import traceback
import importlib
import inspect
from pathlib import Path
from dotenv import load_dotenv
from utils import reddit

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("LoanCentral.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("LoanCentral")

# Multi-subreddit support
SUBREDDITS = os.getenv("SUBREDDITS", os.getenv("SUBREDDIT", "")).replace(" ", "").split(",")
SUBREDDITS = [s for s in SUBREDDITS if s]
if SUBREDDITS:
    subreddit_str = "+".join(SUBREDDITS)
else:
    logger.warning("No subreddits specified. Falling back to single SUBREDDIT env var.")
    subreddit_str = os.getenv("SUBREDDIT", "")

def load_schema():
    """Load and parse SQL schema from schema.sql file"""
    schema_file = Path("schema.sql")
    
    if not schema_file.exists():
        logger.error("schema.sql file not found")
        return None
    
    try:
        with open(schema_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Extract SQL statements - look for statements ending with semicolon
        sql_statements = []
        
        # Split by semicolons and clean up each statement
        raw_statements = content.split(';')
        
        for statement in raw_statements:
            # Clean up the statement
            cleaned = statement.strip()
            
            # Skip empty statements and comments
            if not cleaned or cleaned.startswith('--') or cleaned.startswith('#'):
                continue
            
            # Remove comment lines from the statement
            lines = []
            for line in cleaned.split('\n'):
                line = line.strip()
                if line and not line.startswith('--') and not line.startswith('#'):
                    lines.append(line)
            
            if lines:
                final_statement = ' '.join(lines)
                if final_statement:
                    sql_statements.append(final_statement + ';')
        
        logger.info(f"Loaded {len(sql_statements)} SQL statements from schema.sql")
        return sql_statements
        
    except Exception as e:
        logger.error(f"Error loading schema.sql: {e}")
        logger.error(traceback.format_exc())
        return None

# Initialize database tables if they don't exist
def init_database():
    """Initialize database using schema.sql file"""
    from utils import get_db_connection
    conn = get_db_connection()
    if not conn:
        return False
    
    # Load schema from file
    sql_statements = load_schema()
    if not sql_statements:
        logger.error("Failed to load schema, falling back to hardcoded schema")
        return init_database_fallback(conn)
    
    cur = conn.cursor()
    try:
        # Execute each SQL statement from schema
        for statement in sql_statements:
            if statement.strip():
                logger.debug(f"Executing: {statement[:100]}...")
                cur.execute(statement)
        
        conn.commit()
        logger.info("Database initialized successfully using schema.sql")
        return True
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Database initialization error: {e}")
        logger.error(traceback.format_exc())
        return False
    finally:
        cur.close()
        conn.close()

def init_database_fallback(conn):
    """Fallback database initialization with hardcoded schema"""
    logger.warning("Using fallback hardcoded schema")
    
    cur = conn.cursor()
    try:
        # Create loans table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS loans (
                id SERIAL PRIMARY KEY,
                loan_id TEXT UNIQUE,
                lender TEXT NOT NULL,
                borrower TEXT NOT NULL,
                amount NUMERIC NOT NULL,
                currency TEXT NOT NULL,
                date_created TIMESTAMP NOT NULL,
                original_thread TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                amount_repaid NUMERIC DEFAULT 0,
                last_updated TIMESTAMP
            )
        ''')
        
        # Create users table to track user statistics
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                loans_as_borrower INTEGER DEFAULT 0,
                loans_as_lender INTEGER DEFAULT 0,
                amount_borrowed NUMERIC DEFAULT 0,
                amount_lent NUMERIC DEFAULT 0,
                amount_repaid NUMERIC DEFAULT 0,
                unpaid_loans INTEGER DEFAULT 0,
                unpaid_amount NUMERIC DEFAULT 0,
                last_updated TIMESTAMP
            )
        ''')

        # Create indexes for better performance
        cur.execute('''
            CREATE INDEX IF NOT EXISTS idx_loans_lender ON loans(lender);
        ''')
        cur.execute('''
            CREATE INDEX IF NOT EXISTS idx_loans_borrower ON loans(borrower);
        ''')
        cur.execute('''
            CREATE INDEX IF NOT EXISTS idx_loans_status ON loans(status);
        ''')
        cur.execute('''
            CREATE INDEX IF NOT EXISTS idx_loans_date_created ON loans(date_created);
        ''')
        
        conn.commit()
        logger.info("Database initialized successfully using fallback schema")
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Database initialization error: {e}")
        logger.error(traceback.format_exc())
        return False
    finally:
        cur.close()
        conn.close()

# Simple in-memory rate limiter: max 5 commands per user per 60 seconds
_rate_limit_window = 60
_rate_limit_max = 5
_user_command_times: dict = {}

# Comments processed counter — flushed to DB by keep_alive()
_processed_count: int = 0

def _is_rate_limited(username: str) -> bool:
    now = time.time()
    times = _user_command_times.get(username, [])
    times = [t for t in times if now - t < _rate_limit_window]
    if len(times) >= _rate_limit_max:
        return True
    times.append(now)
    _user_command_times[username] = times
    return False


# Dynamic command loading system
class CommandManager:
    def __init__(self):
        self.commands = {}
        self.load_commands()
    
    def load_commands(self):
        """Load all command modules from the commands directory"""
        commands_dir = Path("commands")
        if not commands_dir.exists():
            # Fallback to current directory
            commands_dir = Path(".")
        
        command_files = list(commands_dir.glob("*_command.py"))
        
        if not command_files:
            logger.warning("No command files found")
            return
        
        for command_file in command_files:
            try:
                # Import the module
                module_name = command_file.stem
                if commands_dir.name == "commands":
                    spec = importlib.util.spec_from_file_location(f"commands.{module_name}", command_file)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                else:
                    spec = importlib.util.spec_from_file_location(module_name, command_file)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                
                # Look for the standard process function names
                possible_func_names = [
                    f"process_{module_name}",  # process_confirm_command
                    f"process_{module_name.replace('_command', '')}_command",  # process_confirm_command
                    "process_command",  # Generic name
                ]
                
                process_func = None
                for func_name in possible_func_names:
                    if hasattr(module, func_name):
                        process_func = getattr(module, func_name)
                        break
                
                if process_func:
                    # Get command trigger from module
                    trigger = getattr(module, 'COMMAND_TRIGGER', f"$unknown")
                    
                    self.commands[trigger.lower()] = process_func
                    logger.info(f"Loaded command: {trigger} from {module_name} using function {process_func.__name__}")
                else:
                    logger.warning(f"No suitable process function found in {module_name}. Tried: {possible_func_names}")
                        
            except Exception as e:
                logger.error(f"Error loading command from {command_file}: {e}")
                logger.error(traceback.format_exc())
    
    def process_comment(self, comment):
        """Process a comment and check if it matches any commands"""
        global _processed_count
        if comment.author is None or comment.author.name.lower() == os.getenv("REDDIT_USERNAME").lower():
            return

        body_lower = comment.body.lower()
        _processed_count += 1

        # Check each command trigger
        for trigger, command_func in self.commands.items():
            if trigger in body_lower:
                username = comment.author.name.lower()
                if _is_rate_limited(username):
                    logger.warning(f"Rate limit hit for u/{username} on {trigger} — skipping")
                    return
                try:
                    logger.info(f"Processing command {trigger} from user {comment.author.name}")
                    command_func(comment)
                except Exception as e:
                    logger.error(f"Error processing command {trigger}: {e}")
                    logger.error(traceback.format_exc())
                break  # Only process one command per comment

# Create global command manager
command_manager = CommandManager()

# Handle new posts
def handle_new_post(post):
    """Process a new [REQ] or [PRE] post"""
    try:
        logger.info(f"Processing new post: {post.id} - {post.title}")
        
        # Generate loan history information for the poster
        username = post.author.name
        user_info = generate_user_info(username)
        
        # Reply to the post with the user's loan information
        post.reply(user_info)
        logger.info(f"Successfully commented on post {post.id} for user {username}")
        
    except Exception as e:
        logger.error(f"Error handling new post {post.id}: {e}")
        logger.error(traceback.format_exc())

# Generate loan history information for a user
def generate_user_info(username):
    """Generate loan history summary posted on [REQ]/[PRE] threads."""
    from services import get_user_profile, calculate_health_score
    from config import DASHBOARD_URL

    profile, error = get_user_profile(username)
    if error or not profile:
        return f"Could not retrieve information for u/{username}."

    if profile["loans_as_borrower"] == 0 and profile["loans_as_lender"] == 0:
        return (
            f"**LoanCentral record for u/{username}:**\n\n"
            f"No loan history found in this system.\n\n"
            f"[View on LoanCentral Dashboard]({DASHBOARD_URL})"
        )

    score, label = calculate_health_score(profile)
    borrowed = float(profile["amount_borrowed"])
    repaid = float(profile["amount_repaid"])
    repay_pct = round(repaid / borrowed * 100, 1) if borrowed > 0 else 100.0

    lines = [
        f"**LoanCentral record for u/{username}:**\n",
        f"|Health Score|Loans as Borrower|Repaid|Unpaid|",
        f"|:--:|:--:|:--:|:--:|",
        f"|**{score}/100** ({label})|{profile['loans_as_borrower']}|"
        f"{profile['loans_as_borrower'] - profile['unpaid_loans']}|{profile['unpaid_loans']}|\n",
        f"|Total Borrowed|Total Repaid|Repayment Rate|Active Loans|",
        f"|:--:|:--:|:--:|:--:|",
        f"|${borrowed:.2f}|${repaid:.2f}|{repay_pct}%|{profile['active_loans']}|\n",
    ]

    if profile["unpaid_loans"] > 0:
        lines.append(
            f"⚠️ u/{username} has **{profile['unpaid_loans']} unpaid loan(s)** "
            f"totalling ${float(profile['unpaid_amount']):.2f}.\n"
        )

    lines.append(f"[Full profile on LoanCentral Dashboard]({DASHBOARD_URL})")
    return "\n".join(lines)

# Function to keep the bot alive
def keep_alive():
    global _processed_count
    while True:
        try:
            logger.info("Keep-alive heartbeat")
            try:
                from services import update_bot_heartbeat
                delta = _processed_count
                _processed_count = 0
                update_bot_heartbeat(delta)
            except Exception as hb_err:
                logger.error(f"Heartbeat update failed: {hb_err}")
            time.sleep(300)  # 5-minute heartbeat
        except Exception as e:
            logger.error(f"Error in keep_alive: {e}")
            logger.error(traceback.format_exc())

# Main bot loop with error handling and reconnection
def comment_monitor():
    while True:
        try:
            subreddit = reddit.subreddit(subreddit_str)
            
            logger.info(f"Starting comment stream for subreddits: {subreddit_str}")
            for comment in subreddit.stream.comments(skip_existing=True):
                command_manager.process_comment(comment)
                    
        except Exception as e:
            logger.error(f"Error in comment stream: {e}")
            logger.error(traceback.format_exc())
            logger.info("Reconnecting in 60 seconds...")
            time.sleep(60)

# Create a set to track posts that have already been processed
processed_posts = set()

# Post monitor with error handling and reconnection
def post_monitor():
    while True:
        try:
            subreddit = reddit.subreddit(subreddit_str)
            
            logger.info(f"Starting post stream for subreddits: {subreddit_str}")
            for post in subreddit.stream.submissions(skip_existing=True):
                if post.id in processed_posts:
                    logger.info(f"Skipping already processed post: {post.id}")
                    continue
                    
                if "[req]" in post.title.lower() or "[pre]" in post.title.lower():
                    handle_new_post(post)
                    processed_posts.add(post.id)
                    
                    if len(processed_posts) > 1000:
                        to_remove = list(processed_posts)[:100]
                        for post_id in to_remove:
                            processed_posts.remove(post_id)
                    
        except Exception as e:
            logger.error(f"Error in post stream: {e}")
            logger.error(traceback.format_exc())
            logger.info("Reconnecting in 60 seconds...")
            time.sleep(60)

if __name__ == "__main__":
    if not init_database():
        sys.exit("Failed to initialize database, exiting")

    # Startup heartbeat + Discord ping
    try:
        from services import update_bot_heartbeat
        update_bot_heartbeat(0)
    except Exception as _e:
        logger.warning(f"Initial heartbeat failed: {_e}")

    try:
        from notifications import notify_discord
        notify_discord(f"\U0001f7e2 **LoanCentral bot started** — watching r/{subreddit_str}")
    except Exception as _e:
        logger.warning(f"Startup Discord ping failed: {_e}")

    # Start all threads
    threading.Thread(target=post_monitor, daemon=False).start()
    threading.Thread(target=keep_alive, daemon=False).start()
    comment_monitor()