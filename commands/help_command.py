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

| Command | Description |
|:---|:---|
| `$status` | Check if the bot and database are online |
| `$mystats` | Your own loan stats + health score |
| `$check u/username` | Another user's stats (borrower + lender history) |
| `$leaderboard` | Top lenders by volume & top borrowers by repayment rate |
| `$report u/username [reason]` | Report a user to mods via modmail |
| `$apply amount CURR [reason]` | Post a loan request (borrowers seeking lenders) |
| `$apply cancel #id` | Cancel your pending loan request |
| `$request lender [reason]` | Request Verified Lender flair |
| `$dispute loan_id [reason]` | Dispute an unpaid mark on your loan |

---

## Lender Commands *(Verified Lender flair required)*

| Command | Description |
|:---|:---|
| `$loan amt CURR u/borrower` | Record a new loan |
| `$loan … due:30d` | Record with due date (30d, 2w, 1m, etc.) |
| `$paid_with_id loan_id amt CURR` | Record a repayment |
| `$paid loan_id amt CURR` | Alias for `$paid_with_id` |
| `$unpaid loan_id` | Mark a loan as unpaid |
| `$refunded loan_id` | Mark a loan as refunded/cancelled |
| `$forgive loan_id` | Forgive/waive a loan (removes debt from borrower's record) |
| `$outstanding` | List all your active/partially-repaid loans and amounts owed |
| `$remind loan_id [msg]` | Send a payment reminder DM to a borrower |

---

## Mod-Only Commands

| Command | Description |
|:---|:---|
| `$ban u/username [reason]` | Ban a user from bot commands |
| `$unban u/username` | Lift a bot ban |
| `$warn u/username [reason]` | Send a formal warning DM + log to mod notes |
| `$note u/username [text]` | Add an internal mod note (not visible to users) |

---

**Dashboard:** {DASHBOARD_URL}
*Full loan history, health scores, CSV export, SMS reminders, overdue tracker, disputes, analytics.*
"""

    comment.reply(help_text)
    logger.info(f"Help sent to u/{comment.author.name}")
