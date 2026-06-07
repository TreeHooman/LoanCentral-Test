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

All history, health scores, stats, and mod tools are on the **[LoanCentral Dashboard]({DASHBOARD_URL})**.

---

## Anyone Can Use

**Check your own stats**
`$mystats`

**Check another user's stats**
`$check u/[username]`

**Post a loan request (borrowers looking for lenders)**
`$apply [amount] [currency] [optional reason]`
Example: `$apply 100 USD need help with rent`

**Cancel a pending loan request**
`$apply cancel #[id]`
Example: `$apply cancel #42`

**Community leaderboard**
`$leaderboard`

**Report a user to mods**
`$report u/[username] [optional reason]`

**Request lender access**
`$request lender [optional reason]`
Example: `$request lender I have been lending on r/borrow for 2 years`

---

## Lender Commands *(Verified Lender flair required)*

**Record a new loan**
`$loan [amount] [currency] u/[borrower]`
Optional due date: `$loan 50 USD u/borrower due:30d` *(30d / 2w / 1m)*

**Record a repayment**
`$paid_with_id [loan_id] [amount] [currency]`
Alias: `$paid [loan_id] [amount] [currency]`

**Mark a loan as unpaid**
`$unpaid [loan_id]`

**Cancel / refund a loan**
`$refunded [loan_id]`

---

**Dashboard:** {DASHBOARD_URL} — full history, health scores, SMS reminders, loan applications.
**Questions?** Contact the moderators.
"""

    comment.reply(help_text)
    logger.info(f"Help sent to u/{comment.author.name}")
