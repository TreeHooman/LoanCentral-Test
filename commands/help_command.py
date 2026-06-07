import logging

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$help"


def process_help_command(comment):
    """Process $help command — lists all bot commands."""
    if "$help" not in comment.body.lower():
        return

    help_text = """
# LoanCentral Bot Commands

The bot tracks loans. Everything else (history, health scores, stats, mod tools) is on the **[dashboard](https://loancentral.app)** — sign in with Reddit.

---

## Lender Commands

**Record a new loan**
```
$loan [amount] [currency] u/[borrower]
```
*Requires Verified Lender flair. Loan is recorded immediately.*

**Record a repayment received**
```
$paid_with_id [loan_id] [amount] [currency]
```

**Mark a loan as unpaid**
```
$unpaid [loan_id]
```

**Cancel / refund a loan**
```
$refunded [loan_id]
```

---

## Borrower Commands

**Dispute a loan** (flags for mod review)
```
$dispute [loan_id]
```

---

**Dashboard:** https://loancentral.app — view history, health score, active loans.
**Need help?** Contact the moderators.
"""

    comment.reply(help_text)
    logger.info(f"Help sent to u/{comment.author.name}")
