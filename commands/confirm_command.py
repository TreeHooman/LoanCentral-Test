import re
import time
import logging
from datetime import datetime
from decimal import Decimal
from functools import wraps
import traceback

logger = logging.getLogger("LoanCentral")

# Command trigger - this will be used by the CommandManager
COMMAND_TRIGGER = "$confirm"

def confirm_restriction(func):
    """Decorator to prevent duplicate confirmations"""
    @wraps(func)
    def wrapper(comment, *args, **kwargs):
        # Import here to avoid circular imports
        from utils import get_db_connection, reddit
        
        # Check if this is a re-confirmation
        conn = get_db_connection()
        if not conn:
            return func(comment, *args, **kwargs)  # Proceed anyway if we can't check
        
        try:
            cur = conn.cursor()
            # Extract borrower from comment
            borrower = comment.author.name.lower()
            
            # Extract full loan details so duplicate checks only block the same loan.
            confirm_regex = r'\$confirm\s+\/u\/([^\s]+)\s+(\d+(?:\.\d+)?)\s+([A-Z]{3})'
            match = re.search(confirm_regex, comment.body, re.IGNORECASE)
            if not match:
                alt_confirm_regex = r'\$confirm\s+u\/([^\s]+)\s+(\d+(?:\.\d+)?)\s+([A-Z]{3})'
                match = re.search(alt_confirm_regex, comment.body, re.IGNORECASE)
                if not match:
                    return func(comment, *args, **kwargs)  # Can't find lender, let the function handle it
            
            lender = match.group(1).lower()
            amount = Decimal(match.group(2))
            currency = match.group(3).upper()
            if amount <= 0:
                return func(comment, *args, **kwargs)
            post = comment.submission
            thread_url = f"https://www.reddit.com{post.permalink}"
            
            # Check if this loan already exists
            cur.execute('''
                SELECT id FROM loans
                WHERE lender = %s
                    AND borrower = %s
                    AND amount = %s
                    AND currency = %s
                    AND original_thread = %s
                    AND status = 'confirmed'
                ORDER BY date_created DESC
                LIMIT 1
            ''', (lender, borrower, amount, currency, thread_url))
            
            existing = cur.fetchone()
            if existing:
                comment.reply(f"Error: You have already confirmed this loan with u/{lender}.")
                return  # Skip the wrapped function
                
            # Check if commenter is the OP of the post
            if comment.author.name.lower() != post.author.name.lower():
                comment.reply(f"Error: Only the original requester (u/{post.author.name}) can confirm this loan. If you're the requester but using a different account, please contact the moderators.")
                return
                
            return func(comment, *args, **kwargs)  # Everything looks good, proceed with the function
            
        except Exception as e:
            logger.error(f"Error in confirm_restriction: {e}")
            logger.error(traceback.format_exc())
            return func(comment, *args, **kwargs)  # Proceed anyway if there's an error
        finally:
            if conn:
                cur.close()
                conn.close()
    
    return wrapper

def generate_loan_id():
    """Generate a unique loan ID based on current timestamp"""
    current_time = int(time.time())
    return f"{current_time}"

@confirm_restriction
def process_confirm_command(comment):
    """Process $confirm command - confirms a loan and creates database entry"""
    # Import here to avoid circular imports
    from utils import get_db_connection, reddit
    
    # First, search directly in the comment body
    confirm_regex = r'\$confirm\s+\/u\/([^\s]+)\s+(\d+(?:\.\d+)?)\s+([A-Z]{3})'
    match = re.search(confirm_regex, comment.body, re.IGNORECASE)
    
    # If no match, try alternate format without /u/
    if not match:
        alt_confirm_regex = r'\$confirm\s+u\/([^\s]+)\s+(\d+(?:\.\d+)?)\s+([A-Z]{3})'
        match = re.search(alt_confirm_regex, comment.body, re.IGNORECASE)
    
    # If still no match, check for code blocks
    if not match:
        code_block_regex = r'```\s*(.*?)\s*```'
        code_blocks = re.findall(code_block_regex, comment.body, re.DOTALL)
        
        if code_blocks:
            # Try both formats in the code block
            match = re.search(confirm_regex, code_blocks[0], re.IGNORECASE)
            if not match:
                match = re.search(alt_confirm_regex, code_blocks[0], re.IGNORECASE)
    
    if not match:
        return
    
    borrower = comment.author.name.lower()
    lender = match.group(1).lower()
    amount = Decimal(match.group(2))
    currency = match.group(3).upper()

    if amount <= 0:
        comment.reply("Error: Loan amount must be greater than zero.")
        return
    
    # This is where we'll actually create the loan
    loan_id = generate_loan_id()
    post = comment.submission
    thread_url = f"https://www.reddit.com{post.permalink}"
    
    conn = get_db_connection()
    if not conn:
        return
    
    try:
        cur = conn.cursor()
        
        # Insert loan
        cur.execute('''
            INSERT INTO loans 
            (loan_id, lender, borrower, amount, currency, date_created, original_thread, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (loan_id, lender, borrower, amount, currency, datetime.now(), thread_url, 'confirmed'))
        
        db_id = cur.fetchone()[0]
        
        # Update user statistics
        # Update lender stats
        cur.execute('''
            INSERT INTO users 
            (username, loans_as_lender, amount_lent, last_updated)
            VALUES (%s, 1, %s, %s)
            ON CONFLICT (username) 
            DO UPDATE SET 
                loans_as_lender = users.loans_as_lender + 1,
                amount_lent = users.amount_lent + %s,
                last_updated = %s
        ''', (lender, amount, datetime.now(), amount, datetime.now()))
        
        # Update borrower stats
        cur.execute('''
            INSERT INTO users 
            (username, loans_as_borrower, amount_borrowed, last_updated)
            VALUES (%s, 1, %s, %s)
            ON CONFLICT (username) 
            DO UPDATE SET 
                loans_as_borrower = users.loans_as_borrower + 1,
                amount_borrowed = users.amount_borrowed + %s,
                last_updated = %s
        ''', (borrower, amount, datetime.now(), amount, datetime.now()))
        
        conn.commit()
        logger.info(f"Confirmed loan: {borrower} confirmed receiving {amount} {currency} from {lender}")
        
        # Reply to the comment
        reply_text = f'''
Confirmed: u/{borrower} has confirmed receiving {amount:.2f} {currency} from u/{lender}.

If you wish to mark this loan repaid later, you can use:

```
$paid_with_id {db_id} {amount:.2f} {currency}
```

Processing time: {time.time() - comment.created_utc:.4f} seconds

If the loan transaction did not work out and needs to be refunded then the *lender* should reply to this comment with 'Refunded' and moderators will be automatically notified
'''
        comment.reply(reply_text)
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error processing confirm command: {e}")
        logger.error(traceback.format_exc())
    finally:
        cur.close()
        conn.close()
