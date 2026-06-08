import logging

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$help"


def process_help_command(comment):
    """Process $help command — lists all bot commands."""
    if "$help" not in comment.body.lower():
        return

    help_text = """
# LoanCentral Commands

Track loans, health scores, and history on the **[dashboard](https://loancentral.app)**.

---

## Lender

| Command | What it does |
|:--|:--|
| `$loan [amount] [currency] u/[borrower]` | Record a new loan *(Verified Lender flair required)* |
| `$paid [loan_id] [amount] [currency]` | Record a repayment (full or partial) |
| `$unpaid [loan_id]` | Mark loan as unpaid |
| `$refunded [loan_id]` | Cancel / refund a loan |
| `$forgive [loan_id]` | Write off remaining balance (no penalty to borrower) |
| `$remind u/[borrower]` | Send a payment reminder |
| `$remindall` | Reminder to all active borrowers (max 8) |

## Borrower

| Command | What it does |
|:--|:--|
| `$dispute [loan_id]` | Flag a loan for mod review |

## General

| Command | What it does |
|:--|:--|
| `$check u/[username]` | View a user's borrower profile |
| `$balance [loan_id]` | Check remaining balance on a loan |
| `$mystats` | View your own lending/borrowing stats |
| `$leaderboard` | Community top lenders & reliable borrowers |

---

**[Dashboard](https://loancentral.app)** · Questions? Message the mods.
"""

    comment.reply(help_text)
    logger.info(f"Help sent to u/{comment.author.name}")
