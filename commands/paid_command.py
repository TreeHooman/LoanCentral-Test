import re
import logging
from datetime import datetime
from decimal import Decimal
import traceback

logger = logging.getLogger("LoanCentral")

# Command trigger - this will be used by the CommandManager
COMMAND_TRIGGER = "$paid_with_id"

def process_paid_command(comment):
    """Process $paid_with_id command - marks loan as paid by lender"""
    # Import here to avoid circular imports
    from utils import get_db_connection, reddit
    
    # First, check if the command is in a code block and extract it
    code_block_regex = r'```\s*(.*?)\s*```'
    code_blocks = re.findall(code_block_regex, comment.body, re.DOTALL)
    
    # Search in both places - first in the raw comment body, then in code blocks if needed
    paid_regex = r'\$paid_with_id\s+(\d+)\s+(\d+(?:\.\d+)?)\s+([A-Z]{3})'
    match = re.search(paid_regex, comment.body, re.IGNORECASE)
    
    # If no match in raw text, check code blocks
    if not match and code_blocks:
        text_to_search = code_blocks[0]
        match = re.search(paid_regex, text_to_search, re.IGNORECASE)
    
    if not match:
        return
    
    lender = comment.author.name.lower()
    loan_id = match.group(1)
    amount_paid = Decimal(match.group(2))
    currency = match.group(3).upper()

    if amount_paid <= 0:
        comment.reply("Error: Payment amount must be greater than zero.")
        return
    
    conn = get_db_connection()
    if not conn:
        return
    
    try:
        cur = conn.cursor()
        
        # Find the loan by either the internal database id or the public loan_id.
        cur.execute('''
            SELECT id, loan_id, lender, borrower, amount, amount_repaid, currency, status
            FROM loans
            WHERE id::text = %s OR loan_id = %s
            ORDER BY id DESC
            LIMIT 1
        ''', (loan_id, loan_id))
        
        result = cur.fetchone()
        if not result:
            logger.warning(f"No matching loan found for payment: ID {loan_id} by {lender}")
            comment.reply(f"Error: Could not find a loan with ID {loan_id}. Please check the loan ID from the confirmation message.")
            return
        
        db_id, public_loan_id, recorded_lender, borrower, loan_amount, already_repaid, loan_currency, status = result

        if recorded_lender != lender:
            logger.warning(
                f"Payment auth mismatch for loan ID {loan_id}: commenter={lender}, recorded_lender={recorded_lender}"
            )
            comment.reply(
                f"Error: Loan ID {loan_id} exists, but it is recorded under lender u/{recorded_lender}. "
                f"Only that lender can use $paid_with_id for this loan."
            )
            return
        
        # Check if this loan has already been fully repaid
        if status == 'repaid':
            comment.reply(f"Error: This loan (ID {loan_id}) has already been fully repaid.")
            return

        if status == 'refunded':
            comment.reply(f"Error: This loan (ID {loan_id}) has been refunded and cannot be marked paid.")
            return
        
        # Ensure all values are Decimal for calculations
        loan_amount = Decimal(loan_amount) if not isinstance(loan_amount, Decimal) else loan_amount
        already_repaid = Decimal(already_repaid) if not isinstance(already_repaid, Decimal) else already_repaid
        
        if loan_currency != currency:
            comment.reply(f"Error: Currency mismatch. The loan was in {loan_currency}, but you specified {currency}.")
            return

        remaining_before_payment = loan_amount - already_repaid
        if amount_paid > remaining_before_payment:
            comment.reply(
                f"Error: Payment amount {amount_paid:.2f} {currency} exceeds the remaining balance "
                f"of {remaining_before_payment:.2f} {currency}."
            )
            return
        
        # Get loan details before the update for the response
        cur.execute('''
            SELECT lender, borrower, amount, amount_repaid, currency, original_thread
            FROM loans
            WHERE id = %s
        ''', (db_id,))
        loan_before = cur.fetchone()
        
        # Update the loan with the amount paid
        new_repaid_amount = already_repaid + amount_paid
        new_status = 'repaid' if new_repaid_amount >= loan_amount else 'partially_repaid'
        
        cur.execute('''
            UPDATE loans
            SET amount_repaid = %s,
                status = %s,
                last_updated = %s
            WHERE id = %s
        ''', (new_repaid_amount, new_status, datetime.now(), db_id))
        
        # Update user statistics
        cur.execute('''
            UPDATE users
            SET amount_repaid = amount_repaid + %s,
                last_updated = %s
            WHERE username = %s
        ''', (amount_paid, datetime.now(), borrower))
        
        # If this was marked unpaid, reduce only the remaining unpaid balance affected by this payment.
        if status == 'unpaid':
            if new_status == 'repaid':
                cur.execute('''
                    UPDATE users
                    SET unpaid_loans = GREATEST(unpaid_loans - 1, 0),
                        unpaid_amount = GREATEST(unpaid_amount - %s, 0),
                        last_updated = %s
                    WHERE username = %s
                ''', (amount_paid, datetime.now(), borrower))
            else:
                cur.execute('''
                    UPDATE users
                    SET unpaid_amount = GREATEST(unpaid_amount - %s, 0),
                        last_updated = %s
                    WHERE username = %s
                ''', (amount_paid, datetime.now(), borrower))
        
        # Get loan details after the update
        cur.execute('''
            SELECT lender, borrower, amount, amount_repaid, currency, original_thread
            FROM loans
            WHERE id = %s
        ''', (db_id,))
        loan_after = cur.fetchone()
        
        conn.commit()
        logger.info(f"Payment recorded: {borrower} repaid {amount_paid} {currency} to {lender}")
        
        # Generate the response message
        response = f"u/{borrower} has now repaid u/{lender} {amount_paid:.2f} {currency}.\n\n"
        response += "Loan before this transaction:\n\n"
        response += "|Lender|Borrower|Amount Given|Amount Repaid|Unpaid?|Original Thread|\n"
        response += "|---|---|---|---|---|---|\n"
        response += f"|{loan_before[0]}|{loan_before[1]}|{loan_before[2]:.2f} {loan_before[4]}|{loan_before[3]:.2f} {loan_before[4]}|{'Yes' if loan_before[3] < loan_before[2] else 'No'}|[Link]({loan_before[5]})|\n\n"
        
        response += "Loan after this transaction:\n\n"
        response += "|Lender|Borrower|Amount Given|Amount Repaid|Unpaid?|Original Thread|\n"
        response += "|---|---|---|---|---|---|\n"
        response += f"|{loan_after[0]}|{loan_after[1]}|{loan_after[2]:.2f} {loan_after[4]}|{loan_after[3]:.2f} {loan_after[4]}|{'Yes' if loan_after[3] < loan_after[2] else 'No'}|[Link]({loan_after[5]})|\n\n"
        
        remaining = loan_amount - new_repaid_amount
        if remaining > 0:
            response += f"amount specified: {amount_paid:.2f} {currency}, remaining: {remaining:.2f} {currency}"
        else:
            response += f"amount specified: {amount_paid:.2f} {currency}, remaining: 0.00 {currency}"
        
        comment.reply(response)
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error processing paid command: {e}")
        logger.error(traceback.format_exc())
    finally:
        cur.close()
        conn.close()
