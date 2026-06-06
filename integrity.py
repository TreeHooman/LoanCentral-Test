from collections import defaultdict
from decimal import Decimal


VALID_LOAN_STATUSES = {"confirmed", "partially_repaid", "repaid", "unpaid", "refunded"}


def _money(value):
    return value if isinstance(value, Decimal) else Decimal(str(value or "0"))


def calculate_user_totals(loans):
    totals = defaultdict(
        lambda: {
            "loans_as_borrower": 0,
            "loans_as_lender": 0,
            "amount_borrowed": Decimal("0"),
            "amount_lent": Decimal("0"),
            "amount_repaid": Decimal("0"),
            "unpaid_loans": 0,
            "unpaid_amount": Decimal("0"),
        }
    )

    for loan in loans:
        if loan.get("status") == "refunded":
            continue

        lender = loan["lender"]
        borrower = loan["borrower"]
        amount = _money(loan["amount"])
        amount_repaid = _money(loan.get("amount_repaid"))

        totals[lender]["loans_as_lender"] += 1
        totals[lender]["amount_lent"] += amount
        totals[borrower]["loans_as_borrower"] += 1
        totals[borrower]["amount_borrowed"] += amount
        totals[borrower]["amount_repaid"] += amount_repaid

        if loan.get("status") == "unpaid":
            totals[borrower]["unpaid_loans"] += 1
            totals[borrower]["unpaid_amount"] += max(amount - amount_repaid, Decimal("0"))

    return dict(totals)


def find_integrity_issues(loans, users):
    issues = []

    for loan in loans:
        loan_id = loan.get("id", loan.get("loan_id", "unknown"))
        amount = _money(loan.get("amount"))
        amount_repaid = _money(loan.get("amount_repaid"))
        status = loan.get("status")

        if status not in VALID_LOAN_STATUSES:
            issues.append(f"Loan {loan_id}: invalid status '{status}'")

        if amount <= 0:
            issues.append(f"Loan {loan_id}: amount must be greater than zero")

        if amount_repaid < 0:
            issues.append(f"Loan {loan_id}: amount_repaid cannot be negative")

        if amount_repaid > amount:
            issues.append(f"Loan {loan_id}: amount_repaid exceeds amount")

        if status == "repaid" and amount_repaid < amount:
            issues.append(f"Loan {loan_id}: status repaid but amount is not fully repaid")

        if status == "unpaid" and amount_repaid >= amount:
            issues.append(f"Loan {loan_id}: status unpaid but loan is fully repaid")

    expected_users = calculate_user_totals(loans)
    usernames = set(users) | set(expected_users)
    numeric_fields = (
        "loans_as_borrower",
        "loans_as_lender",
        "amount_borrowed",
        "amount_lent",
        "amount_repaid",
        "unpaid_loans",
        "unpaid_amount",
    )

    for username in sorted(usernames):
        actual = users.get(username, {})
        expected = expected_users.get(username, {})
        for field in numeric_fields:
            actual_value = _money(actual.get(field)) if field.startswith("amount") or field == "unpaid_amount" else actual.get(field, 0)
            expected_value = expected.get(field, Decimal("0") if field.startswith("amount") or field == "unpaid_amount" else 0)
            if actual_value != expected_value:
                issues.append(
                    f"User {username}: {field} is {actual_value}, expected {expected_value}"
                )

    return issues
