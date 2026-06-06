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

**Announcing a Loan Offer**
```
$loan [amount] [currency]
```
Example: `$loan 50 USD`
*Note: Only users with 'Verified Lender' flair can use this command*

**Recording a Repayment Received**
```
$paid_with_id [loan_id] [amount] [currency]
```
Example: `$paid_with_id 123 50 USD`
Use the loan ID shown in the bot's confirmation message.

**Marking a Loan as Unpaid**
```
$unpaid [loan_id] u/[borrower_username]
```
Example: `$unpaid 123 u/borrower`
Use the loan ID shown in the bot's confirmation message.

**Refunding a Loan**
```
$refunded u/[borrower_username] [amount] [currency]
```
Example: `$refunded u/borrower 50 USD`
Marks the loan as cancelled/refunded and reverses stats.

## For Borrowers

**Confirming a Loan**
```
$confirm /u/[lender_username] [amount] [currency]
```
Example: `$confirm /u/lender 50 USD`
Must be posted in your own loan request thread.

**Recording a Repayment Made**
```
$repaid [loan_id] [amount] [currency]
```
Example: `$repaid 123 50 USD`
Use the loan ID shown in the bot's confirmation message.

## General Commands

**User Statistics**
```
$stats u/[username]
```
Example: `$stats u/username` — shows Reddit account activity and history.

**User Health Rating**
```
$health u/[username]
```
Example: `$health u/username` — shows repayment health score and loan history.

**Contact Moderators**
```
$mods [optional message]
```
Example: `$mods I need help with loan #123` — sends an alert to the mod team.

**Help**
```
$help
```
Shows this help message.

For any questions or issues, please contact the moderators directly.
"""
    
    comment.reply(help_text)
    logger.info(f"Help command processed for user {comment.author.name}")
