import re
import logging
from decimal import Decimal
import traceback

logger = logging.getLogger("LoanCentral")

# Command trigger - this will be used by the CommandManager
COMMAND_TRIGGER = "$health"

def process_health_command(comment):
    """Process $health command"""
    # Import here to avoid circular imports
    from utils import get_db_connection, reddit
    
    # Check for $health command format
    m = re.search(r"\$health\s+(?:/u/|u/)([^\s]+)", comment.body, re.IGNORECASE)
    if not m:
        return
    
    username = m.group(1).lower()
    conn = get_db_connection()
    if not conn:
        return
    
    try:
        cur = conn.cursor()
        
        # Get user loan statistics
        cur.execute('''
            SELECT 
                COALESCE(loans_as_borrower, 0) as loans_as_borrower,
                COALESCE(amount_borrowed, 0) as amount_borrowed,
                COALESCE(amount_repaid, 0) as amount_repaid,
                COALESCE(unpaid_loans, 0) as unpaid_loans
            FROM users
            WHERE username = %s
        ''', (username,))
        
        user_stats = cur.fetchone()
        if not user_stats or user_stats[0] == 0:
            comment.reply(f"# Health Report for u/{username}\n\nThis user has no loan history as a borrower.")
            logger.info(f"Health report generated for user {username} (no history)")
            return
        
        total_loans, total_borrowed, total_repaid, unpaid_loans = user_stats
        paid_loans = total_loans - unpaid_loans
        
        # Calculate health metrics - make sure these are Decimal objects for consistency
        # Convert to Decimal before division to avoid float precision issues
        loan_ratio = Decimal(paid_loans) / Decimal(total_loans) if total_loans > 0 else Decimal('0')
        payment_ratio = Decimal(total_repaid) / Decimal(total_borrowed) if total_borrowed > 0 else Decimal('0')
        
        # Now both are Decimal objects, so multiplication works properly
        health_score = int((loan_ratio * Decimal('0.7') + payment_ratio * Decimal('0.3')) * 100)
        
        # Generate improved progress bars with shell outline
        def generate_progress_bar(value, max_value=1.0, length=20):
            # Convert Decimal to float for this calculation
            if isinstance(value, Decimal):
                value = float(value)
            filled = int(value * length)
            empty = length - filled
            
            # Return a bar with both filled and empty portions visible
            # Using "█" for filled portions and "░" for empty portions
            return "█" * filled + "░" * empty
            
        loan_bar = generate_progress_bar(loan_ratio)
        payment_bar = generate_progress_bar(payment_ratio)
        
        # Determine health status
        if health_score >= 90:
            status = "Excellent"
            description = "This user has an exceptional repayment history."
        elif health_score >= 75:
            status = "Good"
            description = "This user generally repays their loans."
        elif health_score >= 50:
            status = "Fair"
            description = "This user has a mixed repayment history."
        elif health_score >= 25:
            status = "Poor"
            description = "This user has missed several repayments."
        else:
            status = "Very Poor"
            description = "This user rarely completes loan repayments."
        
        # Construct response
        response = f"""
# Health Report for u/{username}

## Overall Health: {status} ({health_score}/100)
{description}

## Loan Completion
{loan_bar} {paid_loans}/{total_loans} loans completed ({int(loan_ratio*100)}%)

## Payment Completion
{payment_bar} ${total_repaid:.2f}/${total_borrowed:.2f} repaid ({int(payment_ratio*100)}%)

## Summary
User has borrowed ${total_borrowed:.2f} across {total_loans} loans.
User has repaid ${total_repaid:.2f} ({int(payment_ratio*100)}% of borrowed amount).
User has {unpaid_loans} unpaid loans remaining.

*This health report is generated automatically based on loan history and may not reflect all circumstances.*
"""
        comment.reply(response)
        logger.info(f"Health report generated for user {username} - Score: {health_score}/100 ({status})")
        
    except Exception as e:
        logger.error(f"Error generating health report: {e}")
        logger.error(traceback.format_exc())
        try:
            comment.reply(f"Error generating health report for u/{username}.")
        except:
            pass
    finally:
        cur.close()
        conn.close()