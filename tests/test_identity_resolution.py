"""
Regression tests for the Reddit-handle vs dashboard-username split.

The bot only ever sees a Reddit handle (`comment.author.name`), while
`user_roles` is keyed on the dashboard username and loans may be recorded under
either name depending on whether the bot or the dashboard wrote the row. Before
resolve_user_identity existed, a lender whose two names differed was invisible
to the bot: lender commands answered "not verified" and $refunded / $unpaid /
$paid_with_id answered "could not find a loan where you are the lender".
"""
import importlib
import os
import sys
import unittest
from decimal import Decimal
from unittest.mock import patch

from tests.support.fakes import (
    FakeComment, FakeDb, FakeReddit, FakeSubmission, FakeSubreddit,
    fake_utils_module, loan_record,
)


# LeftAssociate signs in to the dashboard as "left_associate" but comments on
# Reddit as "LeftAssociate".
DASHBOARD_NAME = "left_associate"
REDDIT_NAME = "LeftAssociate"
LINKS = {DASHBOARD_NAME: REDDIT_NAME}


def linked_db(**kwargs):
    kwargs.setdefault("reddit_links", LINKS)
    kwargs.setdefault("verified_lenders", [DASHBOARD_NAME])
    return FakeDb(**kwargs)


def run_command(module_name, func_name, fake_db, body, author_name=REDDIT_NAME):
    subreddit = FakeSubreddit("LoanCentralTest", flair_text="Verified Lender")
    submission = FakeSubmission(author_name="borrower", subreddit=subreddit)
    comment = FakeComment(
        body=body, author_name=author_name,
        submission=submission, subreddit=subreddit,
    )
    fake_reddit = FakeReddit()
    fake_reddit.subreddits["LoanCentralTest"] = subreddit

    with patch.dict(sys.modules, {"utils": fake_utils_module(fake_db, reddit=fake_reddit)}):
        module = importlib.import_module(module_name)
        importlib.reload(module)
        getattr(module, func_name)(comment)
    return comment


class NormalizeUsernameTests(unittest.TestCase):
    def test_strips_decoration_and_case(self):
        from services import normalize_username
        for raw in ("u/LeftAssociate", "/u/LeftAssociate", " LeftAssociate ", "LEFTASSOCIATE"):
            self.assertEqual(normalize_username(raw), "leftassociate")

    def test_empty_input(self):
        from services import normalize_username
        self.assertEqual(normalize_username(None), "")


class ResolveIdentityTests(unittest.TestCase):
    def _resolve(self, fake_db, name):
        import services
        with patch.object(services, "_get_db", fake_db.connection):
            return services.resolve_user_identity(name)

    def test_reddit_handle_resolves_to_dashboard_account(self):
        identity, err = self._resolve(linked_db(), REDDIT_NAME)
        self.assertIsNone(err)
        self.assertEqual(identity["username"], DASHBOARD_NAME)
        self.assertIn(REDDIT_NAME.lower(), identity["aliases"])
        self.assertIn(DASHBOARD_NAME, identity["aliases"])

    def test_dashboard_name_resolves_to_same_account(self):
        identity, err = self._resolve(linked_db(), DASHBOARD_NAME)
        self.assertIsNone(err)
        self.assertEqual(identity["username"], DASHBOARD_NAME)

    def test_unlinked_name_resolves_to_itself(self):
        identity, err = self._resolve(FakeDb(reddit_links={}), "solo_user")
        self.assertIsNone(err)
        self.assertEqual(identity["username"], "solo_user")
        self.assertEqual(identity["aliases"], ["solo_user"])

    def test_ambiguous_link_is_refused_rather_than_guessed(self):
        fake_db = FakeDb(reddit_links={"acct_one": "shared", "acct_two": "shared"})
        identity, err = self._resolve(fake_db, "shared")
        self.assertIsNone(identity)
        self.assertIn("more than one", err)


class VerifiedLenderLookupTests(unittest.TestCase):
    def test_verified_via_linked_reddit_handle(self):
        import services
        fake_db = linked_db()
        with patch.object(services, "_get_db", fake_db.connection):
            is_verified, _details, err = services.get_verified_lender_status(REDDIT_NAME)
        self.assertIsNone(err)
        self.assertTrue(is_verified, "lender verified under their dashboard name must be recognised from Reddit")

    def test_unrelated_user_is_not_verified(self):
        import services
        fake_db = linked_db()
        with patch.object(services, "_get_db", fake_db.connection):
            is_verified, _details, err = services.get_verified_lender_status("someone_else")
        self.assertIsNone(err)
        self.assertFalse(is_verified)


class LoanLookupAcrossNamesTests(unittest.TestCase):
    """Loans booked on the dashboard are stored under the dashboard username."""

    def test_refund_finds_loan_recorded_under_dashboard_name(self):
        fake_db = linked_db(
            loans=[loan_record(db_id=41, lender=DASHBOARD_NAME, amount="100.00")],
            users={
                DASHBOARD_NAME: {"loans_as_lender": 1, "amount_lent": Decimal("100")},
                "borrower": {"loans_as_borrower": 1, "amount_borrowed": Decimal("100")},
            },
        )
        comment = run_command("commands.refund_command", "process_refund_command",
                              fake_db, "$refunded 41")

        self.assertEqual(fake_db.loans[0]["status"], "refunded")
        self.assertIn("marked as refunded", comment.replies[0])

    def test_refund_reverses_stats_on_the_recorded_name(self):
        fake_db = linked_db(
            loans=[loan_record(db_id=41, lender=DASHBOARD_NAME, amount="100.00")],
            users={
                DASHBOARD_NAME: {"loans_as_lender": 1, "amount_lent": Decimal("100")},
                "borrower": {"loans_as_borrower": 1, "amount_borrowed": Decimal("100")},
            },
        )
        run_command("commands.refund_command", "process_refund_command", fake_db, "$refunded 41")

        self.assertEqual(fake_db.users[DASHBOARD_NAME]["loans_as_lender"], 0)
        self.assertEqual(fake_db.users[DASHBOARD_NAME]["amount_lent"], Decimal("0"))

    def test_unpaid_finds_loan_recorded_under_dashboard_name(self):
        fake_db = linked_db(loans=[loan_record(db_id=31, lender=DASHBOARD_NAME)])
        comment = run_command("commands.unpaid_command", "process_unpaid_command",
                              fake_db, "$unpaid 31")

        self.assertEqual(fake_db.loans[0]["status"], "unpaid")
        self.assertNotIn("Could not find a loan", comment.replies[0])

    def test_paid_finds_loan_recorded_under_dashboard_name(self):
        fake_db = linked_db(loans=[loan_record(db_id=12, lender=DASHBOARD_NAME)])
        comment = run_command("commands.paid_command", "process_paid_command",
                              fake_db, "$paid_with_id 12 25 USD")

        self.assertEqual(fake_db.loans[0]["amount_repaid"], Decimal("25"))
        self.assertNotIn("recorded under lender", comment.replies[0])

    def test_a_different_lender_still_cannot_touch_the_loan(self):
        fake_db = FakeDb(
            loans=[loan_record(db_id=41, lender=DASHBOARD_NAME)],
            reddit_links=LINKS,
            verified_lenders=["intruder"],
        )
        comment = run_command("commands.refund_command", "process_refund_command",
                              fake_db, "$refunded 41", author_name="intruder")

        self.assertEqual(fake_db.loans[0]["status"], "confirmed")
        self.assertIn("Could not find a loan", comment.replies[0])


if __name__ == "__main__":
    unittest.main()


class ShadowRowIntegrationTests(unittest.TestCase):
    """Runs against a real SQLite DB — the bug below survived the mocked fakes.

    Any bot command calls update_last_login() with the author's Reddit handle.
    When that inserted a fresh user_roles row keyed on the handle, the new
    unverified 'borrower' row shadowed the lender's real, verified account and
    every later lender command was refused.
    """

    def setUp(self):
        import shutil, tempfile
        import services
        from local_db import get_sqlite_connection

        self._tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(self._tmpdir, "identity.sqlite3")
        self._cleanup = lambda: shutil.rmtree(self._tmpdir, ignore_errors=True)
        self._patcher = patch.object(
            services, "_get_db", lambda: get_sqlite_connection(db_path))
        self._patcher.start()

        import services as svc
        self.svc = svc
        ok, err = svc.set_verified_lender(DASHBOARD_NAME, True, "mod", "verified in test")
        self.assertIsNone(err, f"setup failed: {err}")
        ok, err = svc.link_reddit_username(DASHBOARD_NAME, REDDIT_NAME, "mod")
        self.assertIsNone(err, f"setup failed: {err}")

    def tearDown(self):
        self._patcher.stop()
        self._cleanup()

    def _user_roles(self):
        conn = self.svc._get_db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT username, role, verified_lender, reddit_username FROM user_roles")
            return cur.fetchall()
        finally:
            conn.close()

    def test_setup_created_one_linked_account(self):
        rows = self._user_roles()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], DASHBOARD_NAME)

    def test_bot_activity_does_not_create_a_shadow_row(self):
        self.svc.update_last_login(REDDIT_NAME)
        usernames = [r[0] for r in self._user_roles()]
        self.assertEqual(usernames, [DASHBOARD_NAME],
                         "the Reddit handle must not become a second user_roles row")

    def test_lender_stays_verified_after_bot_activity(self):
        self.svc.update_last_login(REDDIT_NAME)
        is_verified, _details, err = self.svc.get_verified_lender_status(REDDIT_NAME)
        self.assertIsNone(err)
        self.assertTrue(is_verified, "lender must still be verified after using a bot command")

    def test_verified_despite_a_pre_existing_shadow_row(self):
        # Simulates prod data written before the fix.
        conn = self.svc._get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO user_roles (username, role, verified_lender) VALUES (%s, 'borrower', 0)",
                (REDDIT_NAME.lower(),))
            conn.commit()
        finally:
            conn.close()

        is_verified, _details, err = self.svc.get_verified_lender_status(REDDIT_NAME)
        self.assertIsNone(err)
        self.assertTrue(is_verified, "a leftover shadow row must not outrank the linked account")

        identity, err = self.svc.resolve_user_identity(REDDIT_NAME)
        self.assertIsNone(err)
        self.assertEqual(identity["username"], DASHBOARD_NAME)

    def test_unknown_user_still_gets_a_row(self):
        self.svc.update_last_login("brand_new_borrower")
        usernames = {r[0] for r in self._user_roles()}
        self.assertIn("brand_new_borrower", usernames)


class LoanIdCollisionTests(unittest.TestCase):
    """Two loans created in the same second must not collide on loans.loan_id."""

    def setUp(self):
        import shutil, tempfile
        import services
        from local_db import get_sqlite_connection

        self._tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(self._tmpdir, "loans.sqlite3")
        self._cleanup = lambda: shutil.rmtree(self._tmpdir, ignore_errors=True)
        self._patcher = patch.object(
            services, "_get_db", lambda: get_sqlite_connection(db_path))
        self._patcher.start()
        self.svc = services

    def tearDown(self):
        self._patcher.stop()
        self._cleanup()

    def test_ids_are_unique_within_one_second(self):
        with patch.object(self.svc.time, "time", lambda: 1787000000.0):
            ids = {self.svc._generate_loan_id() for _ in range(200)}
        self.assertGreater(len(ids), 150, "ID space within a single second is too small")

    def test_two_loans_in_the_same_second_both_succeed(self):
        with patch.object(self.svc.time, "time", lambda: 1787000000.0):
            first, err1 = self.svc.create_loan(
                "lender_a", "borrower_a", Decimal("50"), "USD", "https://example/1")
            second, err2 = self.svc.create_loan(
                "lender_b", "borrower_b", Decimal("60"), "USD", "https://example/2")

        self.assertIsNone(err1)
        self.assertIsNone(err2, "second loan in the same second must not fail")
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertNotEqual(first, second)

    def test_collision_is_retried_rather_than_surfaced(self):
        # Force every generated ID to collide once, then succeed.
        with patch.object(self.svc.time, "time", lambda: 1787000000.0):
            self.svc.create_loan("lender_a", "borrower_a", Decimal("50"), "USD", "https://example/1")
            taken = self.svc._generate_loan_id
            calls = {"n": 0}

            def colliding():
                calls["n"] += 1
                return "1787000000000" if calls["n"] == 1 else taken()

            with patch.object(self.svc, "_generate_loan_id", colliding):
                self.svc.create_loan("lender_c", "borrower_c", Decimal("10"), "USD", "https://example/3")
                loan_id, err = self.svc.create_loan(
                    "lender_d", "borrower_d", Decimal("20"), "USD", "https://example/4")

        self.assertIsNone(err)
        self.assertIsNotNone(loan_id)
