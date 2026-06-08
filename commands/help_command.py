import logging

logger = logging.getLogger("LoanCentral")

COMMAND_TRIGGER = "$help"


def process_help_command(comment):
    """Process $help command — lists all bot commands."""
    if "$help" not in comment.body.lower():
        return

    help_text = """
# LoanCentral Bot Commands

The bot tracks loans. History, health scores, stats, and mod tools are on the **[dashboard](https://loancentral.app)** — sign in with Reddit.

---

## Lender Commands

**Record a new loan**

    $loan [amount] [currency] u/[borrower]

*Requires Verified Lender flair.*

**Record a repayment**

    $paid_with_id [loan_id] [amount] [currency]

**Mark a loan as unpaid**

    $unpaid [loan_id]

**Cancel / refund a loan**

    $refunded [loan_id]

**Send a payment reminder**

    $remind u/[borrower]
    $remind u/[borrower] [loan_id]

---

## Borrower Commands

**Dispute a loan record** (flags for mod review)

    $dispute [loan_id]

---

## General Commands

**Check a user's borrower profile**

    $check u/[username]

**View your own stats**

    $mystats

**View the community leaderboard**

    $leaderboard

---

**Dashboard:** https://loancentral.app
**Need help?** Contact the moderators.
"""

    comment.reply(help_text)
    logger.info(f"Help sent to u/{comment.author.name}")
