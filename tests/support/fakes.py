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
    def __init__(
        self,
        author_name="borrower",
        subreddit=None,
        permalink="/r/LoanCentralTest/comments/abc/test/",
        title="Test loan request",
    ):
        self.author = FakeAuthor(author_name)
        self.subreddit = subreddit or FakeSubreddit()
        self.permalink = permalink
        self.title = title


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
    def __init__(self, redditors=None):
        self.subreddits = {}
        self.redditors = redditors or {}

    def subreddit(self, display_name):
        if display_name not in self.subreddits:
            self.subreddits[display_name] = FakeSubreddit(display_name)
        return self.subreddits[display_name]

    def redditor(self, username):
        return self.redditors[username]


class FakeRedditComment:
    def __init__(self, created_utc, score=1, subreddit_name="LoanCentralTest"):
        self.created_utc = created_utc
        self.score = score
        self.subreddit = FakeSubreddit(subreddit_name)


class FakeCommentListing:
    def __init__(self, comments):
        self._comments = comments

    def new(self, limit=100):
        return self._comments[:limit]


class FakeRedditor:
    def __init__(
        self,
        comments=None,
        link_karma=10,
        comment_karma=20,
        created_utc=0,
        has_verified_email=True,
    ):
        self.comments = FakeCommentListing(comments or [])
        self.link_karma = link_karma
        self.comment_karma = comment_karma
        self.created_utc = created_utc
        self.has_verified_email = has_verified_email


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

    def find_confirmed_loan(self, lender, borrower, amount=None, currency=None, original_thread=None):
        matches = [
            loan
            for loan in self.loans
            if loan["lender"] == lender
            and loan["borrower"] == borrower
            and loan["status"] == "confirmed"
            and (amount is None or loan["amount"] == amount)
            and (currency is None or loan["currency"] == currency)
            and (original_thread is None or loan["original_thread"] == original_thread)
        ]
        if not matches:
            return None
        return sorted(matches, key=lambda loan: loan["id"], reverse=True)[0]

    def find_loan_for_borrower(self, loan_lookup, borrower, allow_public_id=True):
        loan = self.find_loan(loan_lookup) if allow_public_id else self.find_loan_by_db_id(loan_lookup)
        if not loan or loan["borrower"] != borrower:
            return None
        return loan

    def find_loan_by_db_id(self, db_id):
        db_id = str(db_id)
        for loan in self.loans:
            if str(loan.get("id")) == db_id:
                return loan
        return None

    def find_loan_for_unpaid(self, loan_lookup, lender, borrower, allow_public_id=True):
        loan = self.find_loan(loan_lookup) if allow_public_id else self.find_loan_by_db_id(loan_lookup)
        if not loan or loan["lender"] != lender or loan["borrower"] != borrower:
            return None
        return loan

    def find_loan_for_refund(self, lender, borrower, amount, currency):
        matches = [
            loan
            for loan in self.loans
            if loan["lender"] == lender
            and loan["borrower"] == borrower
            and loan["amount"] == amount
            and loan["currency"] == currency
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

        if normalized.startswith("select id from loans where lender") and "status = 'confirmed'" in normalized:
            if len(params) == 5:
                lender, borrower, amount, currency, original_thread = params
                loan = self.fake_db.find_confirmed_loan(lender, borrower, amount, currency, original_thread)
            else:
                lender, borrower = params
                loan = self.fake_db.find_confirmed_loan(lender, borrower)
            self.last_result = None if not loan else (loan["id"],)
            return

        if normalized.startswith("select lender, amount, amount_repaid"):
            db_id, borrower = params
            allow_public_id = "loan_id" in normalized
            loan = self.fake_db.find_loan_for_borrower(db_id, borrower, allow_public_id=allow_public_id)
            self.last_result = None if not loan else (
                loan["lender"],
                loan["amount"],
                loan["amount_repaid"],
                loan["currency"],
                loan["status"],
            )
            return

        if normalized.startswith("select id, lender, amount, amount_repaid"):
            loan_lookup, _loan_lookup_again, borrower = params
            loan = self.fake_db.find_loan_for_borrower(loan_lookup, borrower, allow_public_id=True)
            self.last_result = None if not loan else (
                loan["id"],
                loan["lender"],
                loan["amount"],
                loan["amount_repaid"],
                loan["currency"],
                loan["status"],
            )
            return

        if normalized.startswith("select id, amount, currency, amount_repaid"):
            if len(params) == 4:
                db_id, _db_id_again, lender, borrower = params
                allow_public_id = True
            else:
                db_id, lender, borrower = params
                allow_public_id = "loan_id" in normalized
            loan = self.fake_db.find_loan_for_unpaid(db_id, lender, borrower, allow_public_id=allow_public_id)
            self.last_result = None if not loan else (
                loan["id"],
                loan["amount"],
                loan["currency"],
                loan["amount_repaid"],
                loan["original_thread"],
                loan["status"],
            )
            return

        if normalized.startswith("select id from loans where lender") and "amount = %s" in normalized:
            lender, borrower, amount, currency = params
            loan = self.fake_db.find_loan_for_refund(lender, borrower, amount, currency)
            self.last_result = None if not loan else (loan["id"],)
            return

        if normalized.startswith("select id, status from loans where lender") and "amount = %s" in normalized:
            lender, borrower, amount, currency = params
            loan = self.fake_db.find_loan_for_refund(lender, borrower, amount, currency)
            self.last_result = None if not loan else (loan["id"], loan["status"])
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

        if normalized.startswith("update loans set status = 'unpaid'"):
            _last_updated, db_id = params
            loan = self.fake_db.find_loan(db_id)
            if loan:
                loan["status"] = "unpaid"
            self.last_result = None
            return

        if normalized.startswith("update loans set status = 'refunded'"):
            _last_updated, db_id = params
            loan = self.fake_db.find_loan(db_id)
            if loan:
                loan["status"] = "refunded"
            self.last_result = None
            return

        if normalized.startswith("update users set amount_repaid"):
            amount_paid, _last_updated, username = params
            user = self.fake_db.users.setdefault(username, {})
            user["amount_repaid"] = user.get("amount_repaid", Decimal("0")) + amount_paid
            self.last_result = None
            return

        if normalized.startswith("update users set unpaid_loans = unpaid_loans + 1"):
            unpaid_amount, _last_updated, username = params
            user = self.fake_db.users.setdefault(username, {})
            user["unpaid_loans"] = user.get("unpaid_loans", 0) + 1
            user["unpaid_amount"] = user.get("unpaid_amount", Decimal("0")) + unpaid_amount
            self.last_result = None
            return

        if normalized.startswith("update users set unpaid_loans"):
            loan_amount, _last_updated, username = params
            user = self.fake_db.users.setdefault(username, {})
            user["unpaid_loans"] = max(user.get("unpaid_loans", 0) - 1, 0)
            user["unpaid_amount"] = max(user.get("unpaid_amount", Decimal("0")) - loan_amount, Decimal("0"))
            self.last_result = None
            return

        if normalized.startswith("update users set loans_as_lender"):
            amount, _last_updated, username = params
            user = self.fake_db.users.setdefault(username, {})
            user["loans_as_lender"] = max(user.get("loans_as_lender", 0) - 1, 0)
            user["amount_lent"] = max(user.get("amount_lent", Decimal("0")) - amount, Decimal("0"))
            self.last_result = None
            return

        if normalized.startswith("update users set loans_as_borrower"):
            amount, _last_updated, username = params
            user = self.fake_db.users.setdefault(username, {})
            user["loans_as_borrower"] = max(user.get("loans_as_borrower", 0) - 1, 0)
            user["amount_borrowed"] = max(user.get("amount_borrowed", Decimal("0")) - amount, Decimal("0"))
            self.last_result = None
            return

        if normalized.startswith("select coalesce(loans_as_borrower"):
            username = params[0]
            user = self.fake_db.users.get(username)
            self.last_result = None if not user else (
                user.get("loans_as_borrower", 0),
                user.get("amount_borrowed", Decimal("0")),
                user.get("amount_repaid", Decimal("0")),
                user.get("unpaid_loans", 0),
            )
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
    original_thread="https://www.reddit.com/r/LoanCentralTest/comments/abc/test/",
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
        "original_thread": original_thread,
    }


def fake_utils_module(fake_db, reddit=None):
    return SimpleNamespace(
        reddit=reddit or FakeReddit(),
        get_db_connection=lambda: fake_db.connection(),
    )
