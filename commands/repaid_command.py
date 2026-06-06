import re
import logging
from datetime import datetime
from decimal import Decimal
import traceback

logger = logging.getLogger("LoanCentral")

# Command trigger - this will be used by the CommandManager
COMMAND_TRIGGER = "$repaid"

def process_repaid_command(comment):
    """Process $repaid command - borrower marks their own repayment"""
    # Import here to avoid circular imports
    from utils import get_db_connection, reddit
    
    # Search in raw comment body first
    repaid_regex = r"\$repaid\s+(\d+)\s+(\d+(?:\.\d+)?)\s+([A-Z]{3})"
    match = re.search(repaid_regex, comment.body, re.IGNORECASE)
    
    # If no match, check if the command is in a code block
    if not match:
        code_block_regex = r'```\s*(.*?)\s*```'
        code_blocks = re.findall(code_block_regex, comment.body, re.DOTALL)
        if code_blocks:
            match = re.search(repaid_regex, code_blocks[0], re.IGNORECASE)
    
    if not match: 
        return
        
    borrower = comment.author.name.lower()
    loan_id = match.group(1)
    repay_amt = Decimal(match.group(2))
    currency = match.group(3).upper()
    
    conn = get_db_connection()
    if not conn:
        return
        
    try:
        cur = conn.cursor()
        
        # Verify loan exists and borrower is correct
        cur.execute('''
            SELECT id, lender, amount, amount_repaid, currency, status 
            FROM loans 
            WHERE (id::text = %s OR loan_id = %s) AND borrower=%s
            ORDER BY id DESC
            LIMIT 1
        ''', (loan_id, loan_id, borrower))
        
        res = cur.fetchone()
        if not res:
            comment.reply(f"Error: No loan ID {loan_id} found where you are the borrower.")
            return
            
        db_id, lender, total_amt, already_repaid, loan_currency, status = res
        
        # Check currency match
        if currency != loan_currency:
            comment.reply(f"Error: Currency mismatch. The loan was in {loan_currency}, but you specified {currency}.")
            return
            
        # Check if already fully repaid
        if status == "repaid":
            comment.reply("Error: This loan has already been fully repaid.")
            return

        remaining_before_payment = total_amt - already_repaid
        if repay_amt > remaining_before_payment:
            comment.reply(
                f"Error: Payment amount {repay_amt:.2f} {currency} exceeds the remaining balance "
                f"of {remaining_before_payment:.2f} {currency}."
            )
            return
            
        # Calculate new repayment amount and status
        new_total = already_repaid + repay_amt
        new_status = "repaid" if new_total >= total_amt else "partially_repaid"
        remaining = max(total_amt - new_total, Decimal("0.00"))
        
        # Update loan record
        cur.execute('''
            UPDATE loans 
            SET amount_repaid=%s, status=%s, last_updated=%s 
            WHERE id=%s
        ''', (new_total, new_status, datetime.now(), db_id))
        
        # Update user stats
        cur.execute('''
            UPDATE users 
            SET amount_repaid=amount_repaid+%s, last_updated=%s 
            WHERE username=%s
        ''', (repay_amt, datetime.now(), borrower))
        
        # If this was marked unpaid, reduce only the remaining unpaid balance affected by this payment.
        if status == "unpaid":
            if new_status == "repaid":
                cur.execute('''
                    UPDATE users 
                    SET unpaid_loans=GREATEST(unpaid_loans-1,0), 
                        unpaid_amount=GREATEST(unpaid_amount-%s,0), 
                        last_updated=%s 
                    WHERE username=%s
                ''', (repay_amt, datetime.now(), borrower))
            else:
                cur.execute('''
                    UPDATE users 
                    SET unpaid_amount=GREATEST(unpaid_amount-%s,0), 
                        last_updated=%s 
                    WHERE username=%s
                ''', (repay_amt, datetime.now(), borrower))
        
        conn.commit()
        
        # Prepare response
        response = f"u/{borrower} repaid {repay_amt:.2f} {currency} to u/{lender}.\n\n"
        response += f"Payment of {repay_amt:.2f} {currency} recorded.\n\n"
        response += "|Loan ID|Lender|Borrower|Original Amount|Amount Repaid|Remaining|\n"
        response += "|:--:|:--:|:--:|:--:|:--:|:--:|\n"
        response += f"|{db_id}|{lender}|{borrower}|{total_amt:.2f} {currency}|{new_total:.2f} {currency}|{remaining:.2f} {currency}|\n\n"
        
        if remaining > 0:
            response += f"You still need to repay {remaining:.2f} {currency} to complete this loan."
        else:
            response += "This loan has now been fully repaid! Thank you!"
        
        comment.reply(response)
        logger.info(f"Repayment processed: {borrower} repaid {repay_amt:.2f} {currency} to {lender}")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error processing repaid command: {e}")
        logger.error(traceback.format_exc())
    finally:
        cur.close()
        conn.close()
