from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace


class FakeAuthor:
    def __init__(self, name):
        self.name = name


class FakeSubreddit:
    def __init__(self, display_name="LoanCentralTest", flair_text="Verified Lender"):
        self.display_name = display_name
        self._flair_text = flair_text
        self.messages = []

    def flair(self, redditor=None):
        return [{"flair_text": self._flair_text}]

    def message(self, subject, message):
        self.messages.append({"subject": subject, "message": message})


class FakeSubmission:
    def __init__(self, author_name="borrower", subreddit=None, permalink="/r/LoanCentralTest/comments/abc/test/"):
        self.author = FakeAuthor(author_name)
        self.subreddit = subreddit or FakeSubreddit()
        self.permalink = permalink


class FakeComment:
    def __init__(
        self,
        body,
        author_name="lender",
        submission=None,
        subreddit=None,
        parent_comment=None,
        created_utc=0,
        permalink="/r/LoanCentralTest/comments/abc/test/comment/",
    ):
        self.body = body
        self.author = FakeAuthor(author_name)
        self.submission = submission or FakeSubmission(subreddit=subreddit)
        self.subreddit = subreddit or self.submission.subreddit
        self.created_utc = created_utc
        self.permalink = permalink
        self.replies = []
        self._parent_comment = parent_comment

    def reply(self, body):
        self.replies.append(body)
        return body

    def parent(self):
        return self._parent_comment


class FakeReddit:
    def __init__(self):
        self.subreddits = {}

    def subreddit(self, display_name):
        if display_name not in self.subreddits:
            self.subreddits[display_name] = FakeSubreddit(display_name)
        return self.subreddits[display_name]


class FakeDb:
    def __init__(self, loans=None, users=None):
        self.loans = deepcopy(loans or [])
        self.users = deepcopy(users or {})
        self.next_id = max([loan["id"] for loan in self.loans], default=0) + 1

    def connection(self):
        return FakeConnection(self)

    def find_loan(self, loan_lookup):
        loan_lookup = str(loan_lookup)
        matches = [
            loan
            for loan in self.loans
            if str(loan.get("id")) == loan_lookup or str(loan.get("loan_id")) == loan_lookup
        ]
        if not matches:
            return None
        return sorted(matches, key=lambda loan: loan["id"], reverse=True)[0]

    def loan_details(self, db_id):
        loan = self.find_loan(db_id)
        if not loan:
            return None
        return (
            loan["lender"],
            loan["borrower"],
            loan["amount"],
            loan["amount_repaid"],
            loan["currency"],
            loan["original_thread"],
        )

    def find_confirmed_loan(self, lender, borrower):
        matches = [
            loan
            for loan in self.loans
            if loan["lender"] == lender
            and loan["borrower"] == borrower
            and loan["status"] == "confirmed"
        ]
        if not matches:
            return None
        return sorted(matches, key=lambda loan: loan["id"], reverse=True)[0]

    def insert_loan(self, loan_id, lender, borrower, amount, currency, date_created, original_thread, status):
        db_id = self.next_id
        self.next_id += 1
        self.loans.append(
            {
                "id": db_id,
                "loan_id": loan_id,
                "lender": lender,
                "borrower": borrower,
                "amount": amount,
                "amount_repaid": Decimal("0"),
                "currency": currency,
                "date_created": date_created,
                "original_thread": original_thread,
                "status": status,
            }
        )
        return db_id


class FakeConnection:
    def __init__(self, fake_db):
        self.fake_db = fake_db
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return FakeCursor(self.fake_db)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class FakeCursor:
    def __init__(self, fake_db):
        self.fake_db = fake_db
        self.last_result = None
        self.closed = False

    def execute(self, query, params=None):
        normalized = " ".join(query.split()).lower()
        params = params or ()

        if normalized.startswith("select id, loan_id, lender, borrower"):
            loan = self.fake_db.find_loan(params[0])
            self.last_result = None if not loan else (
                loan["id"],
                loan["loan_id"],
                loan["lender"],
                loan["borrower"],
                loan["amount"],
                loan["amount_repaid"],
                loan["currency"],
                loan["status"],
            )
            return

        if normalized.startswith("select id from loans where lender"):
            lender, borrower = params
            loan = self.fake_db.find_confirmed_loan(lender, borrower)
            self.last_result = None if not loan else (loan["id"],)
            return

        if normalized.startswith("insert into loans"):
            self.last_result = (self.fake_db.insert_loan(*params),)
            return

        if normalized.startswith("insert into users") and "loans_as_lender" in normalized:
            username, amount, _created, update_amount, _updated = params
            user = self.fake_db.users.setdefault(username, {})
            user["loans_as_lender"] = user.get("loans_as_lender", 0) + 1
            user["amount_lent"] = user.get("amount_lent", Decimal("0")) + update_amount
            self.last_result = None
            return

        if normalized.startswith("insert into users") and "loans_as_borrower" in normalized:
            username, amount, _created, update_amount, _updated = params
            user = self.fake_db.users.setdefault(username, {})
            user["loans_as_borrower"] = user.get("loans_as_borrower", 0) + 1
            user["amount_borrowed"] = user.get("amount_borrowed", Decimal("0")) + update_amount
            self.last_result = None
            return

        if normalized.startswith("select lender, borrower, amount, amount_repaid"):
            self.last_result = self.fake_db.loan_details(params[0])
            return

        if normalized.startswith("update loans set amount_repaid"):
            amount_repaid, status, _last_updated, db_id = params
            loan = self.fake_db.find_loan(db_id)
            if loan:
                loan["amount_repaid"] = amount_repaid
                loan["status"] = status
            self.last_result = None
            return

        if normalized.startswith("update users set amount_repaid"):
            amount_paid, _last_updated, username = params
            user = self.fake_db.users.setdefault(username, {})
            user["amount_repaid"] = user.get("amount_repaid", Decimal("0")) + amount_paid
            self.last_result = None
            return

        if normalized.startswith("update users set unpaid_loans"):
            loan_amount, _last_updated, username = params
            user = self.fake_db.users.setdefault(username, {})
            user["unpaid_loans"] = max(user.get("unpaid_loans", 0) - 1, 0)
            user["unpaid_amount"] = max(user.get("unpaid_amount", Decimal("0")) - loan_amount, Decimal("0"))
            self.last_result = None
            return

        raise AssertionError(f"FakeCursor does not support query: {query}")

    def fetchone(self):
        return self.last_result

    def close(self):
        self.closed = True


def loan_record(
    db_id=1,
    public_id="1700000000",
    lender="lender",
    borrower="borrower",
    amount="100.00",
    amount_repaid="0.00",
    currency="USD",
    status="confirmed",
):
    return {
        "id": db_id,
        "loan_id": public_id,
        "lender": lender,
        "borrower": borrower,
        "amount": Decimal(amount),
        "amount_repaid": Decimal(amount_repaid),
        "currency": currency,
        "status": status,
        "original_thread": "https://www.reddit.com/r/LoanCentralTest/comments/abc/test/",
    }


def fake_utils_module(fake_db):
    return SimpleNamespace(
        reddit=FakeReddit(),
        get_db_connection=lambda: fake_db.connection(),
    )
