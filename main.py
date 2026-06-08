import logging
import os
import threading
import sys
import time
import traceback
import importlib
import inspect
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from bot_messages import with_dashboard_link
from utils import reddit, reddit_limiter

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

# Dynamic command loading system
class CommandManager:
    def __init__(self):
        self.commands = {}
        self.recent_commands = {}
        self.cooldown_seconds = int(os.getenv("BOT_COMMAND_COOLDOWN_SECONDS", "15"))
        self.load_commands()

    def _is_rate_limited(self, username, trigger):
        if self.cooldown_seconds <= 0:
            return False
        now = time.time()
        key = (username.lower(), trigger)
        last = self.recent_commands.get(key, 0)
        if now - last < self.cooldown_seconds:
            return True
        self.recent_commands[key] = now
        if len(self.recent_commands) > 5000:
            cutoff = now - 3600
            self.recent_commands = {
                k: ts for k, ts in self.recent_commands.items() if ts >= cutoff
            }
        return False
    
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
        bot_username = (os.getenv("REDDIT_USERNAME") or "").lower()
        if comment.author is None or comment.author.name.lower() == bot_username:
            return
        
        body_lower = comment.body.lower()
        
        # Check each command trigger
        for trigger, command_func in self.commands.items():
            if trigger in body_lower:
                try:
                    if self._is_rate_limited(comment.author.name, trigger):
                        logger.info(f"Rate limited command {trigger} from user {comment.author.name}")
                        return
                    logger.info(f"Processing command {trigger} from user {comment.author.name}")
                    reddit_limiter.wait()
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
        if post.author is None:
            logger.info(f"Skipping deleted/removed post with no author: {post.id}")
            return
        
        # Generate loan history information for the poster
        username = post.author.name
        user_info = generate_user_info(username)
        reply_parts = [user_info]

        if "[req]" in post.title.lower():
            from services import find_duplicate_open_requests, save_loan_request
            duplicates, _ = find_duplicate_open_requests(username, exclude_reddit_post_id=getattr(post, "id", None))
            thread_link = getattr(post, "permalink", "") or ""
            if thread_link and thread_link.startswith("/"):
                thread_link = "https://www.reddit.com" + thread_link
            post_date = datetime.fromtimestamp(getattr(post, "created_utc", time.time()))
            request_id, error = save_loan_request(
                borrower=username,
                title=post.title,
                thread_link=thread_link,
                post_date=post_date,
                reddit_post_id=getattr(post, "id", None),
            )
            if request_id:
                reply_parts.append(
                    f"LoanCentral request ID: `{request_id}`\n\n"
                    "After lender and borrower agree to terms on Reddit, a verified lender can fund it with:\n\n"
                    f"`$fund {request_id} [repay_amount] [currency] [YYYY-MM-DD]`\n\n"
                    "Funding returns a Paid ID for `$paid_with_id`, `$unpaid`, and `$refunded`. "
                    "LoanCentral is a record-keeping tool and does not handle funds."
                )
            elif error:
                logger.info(f"REQ post {post.id} was not saved as a loan request: {error}")

            if duplicates:
                duplicate_ids = ", ".join(d["request_id"] for d in duplicates)
                reply_parts.append(
                    f"Note for moderators: u/{username} already has open request(s): {duplicate_ids}."
                )
        
        # Reply once, with history plus any REQ-ID info, to minimize Reddit API calls.
        reddit_limiter.wait()
        post.reply(with_dashboard_link("\n\n---\n\n".join(reply_parts)))
        logger.info(f"Successfully commented on post {post.id} for user {username}")
        
    except Exception as e:
        logger.error(f"Error handling new post {post.id}: {e}")
        logger.error(traceback.format_exc())

# Generate loan history information for a user
def generate_user_info(username):
    """Generate loan history information for a user."""
    from services import get_user_profile

    profile, error = get_user_profile(username)
    if error or not profile:
        return f"Could not retrieve information for u/{username}"

    response = [f"Here is my information on u/{username}:"]

    if profile["loans_as_borrower"] == 0 and profile["loans_as_lender"] == 0:
        response.append(f"u/{username} has no loan history.")
        return "\n\n".join(response)

    response.append(f"u/{username} has {profile['loans_as_borrower']} loans paid as a borrower, for a total of ${profile['amount_repaid']:.2f}")
    response.append(f"u/{username} has {profile['loans_as_lender']} loans paid as a lender, for a total of ${profile['amount_lent']:.2f}")

    if profile["unpaid_loans"] > 0:
        response.append(f"u/{username} has {profile['unpaid_loans']} loans currently marked unpaid, for a total of ${profile['unpaid_amount']:.2f}")
    else:
        response.append(f"u/{username} has not received any loans which are currently marked unpaid")

    if profile["active_loans"] > 0:
        response.append(f"u/{username} has {profile['active_loans']} outstanding loans as a borrower, for a total of ${profile['active_amount']:.2f}")
    else:
        response.append(f"u/{username} does not have any outstanding loans as a borrower")

    return "\n\n".join(response)

# Function to keep the bot alive
def keep_alive():
    while True:
        try:
            logger.info("Keep-alive heartbeat")
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

    # Start all threads
    threading.Thread(target=post_monitor, daemon=False).start()
    threading.Thread(target=keep_alive, daemon=False).start()
    comment_monitor()
