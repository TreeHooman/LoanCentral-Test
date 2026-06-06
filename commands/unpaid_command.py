import re
import logging
from datetime import datetime
import traceback

logger = logging.getLogger("LoanCentral")

# Command trigger - this will be used by the CommandManager
COMMAND_TRIGGER = "$unpaid"

def process_unpaid_command(comment):
    """Process $unpaid command - lender marks loan as unpaid"""
    # Import here to avoid circular imports
    from utils import get_db_connection, reddit
    
    # Check for command format
    unpaid_regex = r'\$unpaid\s+(\d+)\s+u?\/?([\w-]+)'
    match = re.search(unpaid_regex, comment.body, re.IGNORECASE)
    
    if not match:
        return
    
    lender = comment.author.name.lower()
    loan_id = match.group(1)
    borrower = match.group(2).lower()
    
    conn = get_db_connection()
    if not conn:
        return
    
    try:
        cur = conn.cursor()
        
        # Find the loan and verify the lender owns it
        cur.execute('''
            SELECT id, amount, currency, amount_repaid, original_thread, status
            FROM loans
            WHERE id = %s AND lender = %s AND borrower = %s
        ''', (loan_id, lender, borrower))
        
        result = cur.fetchone()
        if not result:
            logger.warning(f"No matching loan found for unpaid: ID {loan_id} by {lender} for borrower {borrower}")
            comment.reply(f"Error: Could not find a loan with ID {loan_id} where you are the lender and u/{borrower} is the borrower.")
            return
        
        db_id, loan_amount, loan_currency, amount_repaid, thread_url, status = result
        
        # Ensure not already marked as unpaid
        if status == 'unpaid':
            comment.reply(f"This loan has already been marked as unpaid.")
            return
        
        # Update the loan status to unpaid
        cur.execute('''
            UPDATE loans
            SET status = 'unpaid',
                last_updated = %s
            WHERE id = %s
        ''', (datetime.now(), loan_id))
        
        # Update user statistics - increment unpaid count for borrower
        remaining_unpaid = loan_amount - amount_repaid
        cur.execute('''
            UPDATE users
            SET unpaid_loans = unpaid_loans + 1,
                unpaid_amount = unpaid_amount + %s,
                last_updated = %s
            WHERE username = %s
        ''', (remaining_unpaid, datetime.now(), borrower))
        
        conn.commit()
        logger.info(f"Loan marked as unpaid: Loan ID {loan_id} from {lender} to {borrower}")
        
        # Get current subreddit from the comment
        current_subreddit = comment.subreddit.display_name
        
        # Create comprehensive response with details
        response = f"u/{lender} has marked their loan to u/{borrower} as unpaid.\n\n"
        response += "This loan has been recorded as unpaid in the database.\n\n"
        response += "|Lender|Borrower|Amount|Amount Repaid|Date|Original Thread|\n"
        response += "|:--:|:--:|:--:|:--:|:--:|:--:|\n"
        response += f"|{lender}|{borrower}|{loan_amount:.2f} {loan_currency}|{amount_repaid:.2f} {loan_currency}|{datetime.now().strftime('%Y-%m-%d')}|[Link]({thread_url})|\n\n"
        
        # Add unpaid post link using the comment's subreddit instead of hardcoded one
        response += f"If you would like to make a loan unpaid post, [use this link](https://www.reddit.com/r/{current_subreddit}/submit?selftext=true&title=UNPAID:%20/u/{borrower}%20{str(loan_amount)}%20{loan_currency}).\n\n"
        response += "If this is in error, please contact the moderators."
        
        comment.reply(response)
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error processing unpaid command: {e}")
        logger.error(traceback.format_exc())
    finally:
        cur.close()
        conn.close()