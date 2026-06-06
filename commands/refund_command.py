import os
import re
import logging
from datetime import datetime
from decimal import Decimal
import traceback

logger = logging.getLogger("LoanCentral")

# Command trigger - this will be used by the CommandManager
COMMAND_TRIGGER = "$refunded"

def process_refund_command(comment):
    """Process $refunded command"""
    # Import here to avoid circular imports
    from utils import get_db_connection, reddit
    
    # Check if this is a reply to a loan bot comment
    if not comment.parent().author or comment.parent().author.name.lower() != os.getenv("REDDIT_USERNAME").lower():
        return
    
    if "refunded" not in comment.body.lower():
        return
    
    # Extract the loan information from the parent comment
    parent_body = comment.parent().body
    loan_regex = r'u\/([^\s]+) has confirmed receiving (\d+(?:\.\d+)?)\s+([A-Z]{3}) from u\/([^\s\.]+)'
    match = re.search(loan_regex, parent_body)
    
    if not match:
        return
    
    borrower = match.group(1).lower()
    amount = Decimal(match.group(2))
    currency = match.group(3)
    lender = match.group(4).lower()
    
    # Verify the refund command is from the lender
    if comment.author.name.lower() != lender:
        comment.reply("Only the lender can mark a loan as refunded.")
        return
    
    conn = get_db_connection()
    if not conn:
        return
    
    try:
        cur = conn.cursor()
        
        # Find the relevant loan
        cur.execute('''
            SELECT id FROM loans
            WHERE lender = %s AND borrower = %s AND amount = %s AND currency = %s
            ORDER BY date_created DESC
            LIMIT 1
        ''', (lender, borrower, amount, currency))
        
        result = cur.fetchone()
        if not result:
            logger.warning(f"No matching loan found for refund: {lender} to {borrower} for {amount} {currency}")
            comment.reply(f"Error: Could not find a matching loan from you to u/{borrower} for {amount} {currency}.")
            return
        
        loan_id = result[0]

        # Update the loan status to refunded
        cur.execute('''
            UPDATE loans
            SET status = 'refunded',
                last_updated = %s
            WHERE id = %s
        ''', (datetime.now(), loan_id))
        
        # Update user statistics - properly update based on existing values
        cur.execute('''
            UPDATE users
            SET loans_as_lender = GREATEST(loans_as_lender - 1, 0),
                amount_lent = GREATEST(amount_lent - %s, 0),
                last_updated = %s
            WHERE username = %s
        ''', (amount, datetime.now(), lender))
        
        cur.execute('''
            UPDATE users
            SET loans_as_borrower = GREATEST(loans_as_borrower - 1, 0),
                amount_borrowed = GREATEST(amount_borrowed - %s, 0),
                last_updated = %s
            WHERE username = %s
        ''', (amount, datetime.now(), borrower))
        
        conn.commit()
        logger.info(f"Loan refunded: {lender} refunded {amount} {currency} to {borrower}")
        
        # Reply to the comment
        comment.reply(f"Loan marked as refunded. The loan from u/{lender} to u/{borrower} for {amount:.2f} {currency} has been removed from both users' statistics.")
        
        # Notify moderators
        post_subreddit = comment.submission.subreddit.display_name
        subreddit = reddit.subreddit(post_subreddit)
        subject = f"Loan Refunded - {lender} to {borrower}"
        message = f"A loan has been marked as refunded:\n\nLender: u/{lender}\nBorrower: u/{borrower}\nAmount: {amount:.2f} {currency}\n\nLink to comment: https://www.reddit.com{comment.permalink}"
        subreddit.message(subject, message)
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error processing refund command: {e}")
        logger.error(traceback.format_exc())
    finally:
        cur.close()
        conn.close()