import logging

logger = logging.getLogger("LoanCentral")

# Command trigger - this will be used by the CommandManager
COMMAND_TRIGGER = "$help"

def process_help_command(comment):
    """Process $help command"""
    if not "$help" in comment.body.lower():
        return
        
    help_text = """
# LoanCentral Bot Commands

Below are all available commands for interacting with the LoanCentral Bot:

## For Lenders

**Creating a Loan**
```
$loan [amount] [currency]
```
Example: `$loan 50 USD`
*Note: Only users with 'Verified Lender' flair can use this command*

**Marking a Loan as Paid**
```
$paid_with_id [loan_id] [amount] [currency]
```
Example: `$paid_with_id 123 50 USD`

**Marking a Loan as Unpaid**
```
$unpaid [loan_id] [borrower_username]
```
Example: `$unpaid 123 u/borrower`

**Refunding a Loan**
```
$refunded
```
Reply to the loan confirmation comment with this command to mark it as refunded.

**Checking Stats**
```
$stats [username]
```
Example: `$stats u/lender` or just `$stats` for your own stats

**Health Check**
```
$health
```
Check if the bot is functioning properly

**Moderator Commands**
```
$mods
```
View list of moderator commands

## For Borrowers

**Confirming a Loan**
```
$confirm /u/[lender_username] [amount] [currency]
```
Example: `$confirm /u/lender 50 USD`

**Recording a Repayment**
```
$repaid [loan_id] [amount] [currency]
```
Example: `$repaid 123 50 USD`

**Recording a Repayment (Alternative)**
```
$repaid [loan_id] [amount] [currency]
```
Example: `$repaid 123 25 USD`

## General Commands

**User Statistics**
```
$stats u/[username]
```
Example: `$stats u/username`

**User Health Rating**
```
$health u/[username]
```
Example: `$health u/username`

**Help**
```
$help
```
Shows this help message

For any questions or issues, please contact the moderators.
"""
    
    comment.reply(help_text)
    logger.info(f"Help command processed for user {comment.author.name}")