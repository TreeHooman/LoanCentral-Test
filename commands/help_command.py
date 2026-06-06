import logging

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$help"


def process_help_command(comment):
    """Process $help command — lists all bot commands."""
    from config import DASHBOARD_URL

    if "$help" not in comment.body.lower():
        return

    help_text = f"""
# LoanCentral Bot Commands

The bot tracks loans. Everything else (history, health scores, stats, mod tools) is on the **[LoanCentral Dashboard]({DASHBOARD_URL})**.

---

## Lender Commands

**Record a new loan**
```
$loan [amount] [currency] u/[borrower]
```
Example: `$loan 50 USD u/borrower`
*Requires Verified Lender flair. Loan is recorded immediately.*

**Record a repayment received**
```
$paid_with_id [loan_id] [amount] [currency]
```
Example: `$paid_with_id 123 50 USD`

**Mark a loan as unpaid**
```
$unpaid [loan_id]
```
Example: `$unpaid 123`

**Cancel / refund a loan**
```
$refunded [loan_id]
```
Example: `$refunded 123`

---

**View your loan history, health score, and stats:** {DASHBOARD_URL}

**Need help?** Contact the moderators.
"""

    comment.reply(help_text)
    logger.info(f"Help sent to u/{comment.author.name}")
