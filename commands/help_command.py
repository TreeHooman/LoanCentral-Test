import logging

from bot_messages import DASHBOARD_URL, with_dashboard_link

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$help"


def process_help_command(comment):
    """Process $help command - lists all bot commands."""
    if "$help" not in comment.body.lower():
        return

    help_text = f"""
# LoanCentral Bot Commands

The bot tracks loans. Everything else (history, health scores, stats, mod tools) is on the **[dashboard]({DASHBOARD_URL})** - sign in with Reddit.

---

## Lender Commands

**Record a new loan**
```
$loan [amount] [currency] u/[borrower]
```
*Requires LoanCentral verified lender approval and the Reddit Verified Lender flair. Loan is recorded immediately.*

**Fund a REQ code**
```
$fund REQ-0001 [repay_amount] [currency] [YYYY-MM-DD]
```
*Requires LoanCentral verified lender approval and the Reddit Verified Lender flair.*

**Record a repayment received**
```
$paid_with_id [paid_id] [amount] [currency]
```

**Mark a loan as unpaid**
```
$unpaid [paid_id]
```

**Cancel / refund a loan**
```
$refunded [paid_id]
```

---

## Borrower Commands

**Dispute a loan** (flags for mod review)
```
$dispute [paid_id]
```

---

**Dashboard:** {DASHBOARD_URL} - view history, health score, active loans.
**Need help?** Contact the moderators.
"""

    comment.reply(with_dashboard_link(help_text))
    logger.info(f"Help sent to u/{comment.author.name}")
