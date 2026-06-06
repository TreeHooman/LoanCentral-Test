import re
import time
import logging
import os
from datetime import datetime
from decimal import Decimal
import traceback

logger = logging.getLogger("LoanCentral")

# Command trigger - this will be used by the CommandManager
COMMAND_TRIGGER = "$loan"

def generate_loan_id():
    """Generate a unique loan ID based on current timestamp"""
    current_time = int(time.time())
    return f"{current_time}"

def process_loan_command(comment):
    """Process $loan command - creates a loan offer that needs confirmation"""
    # Import here to avoid circular imports
    from utils import get_db_connection, reddit
    
    loan_regex = r'\$loan\s+(\d+(?:\.\d+)?)\s+([A-Z]{3})'
    match = re.search(loan_regex, comment.body, re.IGNORECASE)
    
    if not match:
        return
    
    # Check if user has 'Verified Lender' flair
    lender = comment.author.name.lower()
    subreddit = comment.subreddit
    
    try:
        # Get the user's flair in this subreddit
        user_flair = None
        for flair in subreddit.flair(redditor=comment.author):
            user_flair = flair['flair_text']
            break
        
        # Check if user has 'Verified Lender' flair
        if not user_flair or 'verified lender' not in user_flair.lower():
            comment.reply(f"Error: Only users with 'Verified Lender' flair can issue loans in r/{subreddit.display_name}.")
            return
            
    except Exception as e:
        logger.error(f"Error checking flair for user {lender}: {e}")
        comment.reply("Error: Unable to verify your flair status. Please contact the moderators.")
        return
    
    # Proceed with loan processing for verified lenders
    post = comment.submission
    borrower = post.author.name.lower()
    amount = Decimal(match.group(1))
    currency = match.group(2).upper()
    
    if borrower == lender:
        logger.warning(f"User {lender} attempted to lend to themselves")
        return
    
    loan_id = generate_loan_id()
    thread_url = f"https://www.reddit.com{post.permalink}"
    
    try:
        # Reply to the comment
        reply_text = f'''
I've seen that u/{lender} is offering {amount:.2f} {currency} to u/{borrower}!

u/{borrower} needs to confirm this transaction using:

```
$confirm /u/{lender} {amount:.2f} {currency}
```

The loan will only be registered in the database after confirmation. This helps ensure that the money was actually sent and received.
'''
        comment.reply(reply_text)
        logger.info(f"Loan offer recorded: {lender} is offering {amount} {currency} to {borrower}")
        
    except Exception as e:
        logger.error(f"Error processing loan command: {e}")
        logger.error(traceback.format_exc())