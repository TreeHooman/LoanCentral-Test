"""$login -> DM'd setup link -> connect Google -> sign in with Google.

Runs the bot's real entry point and the dashboard's real routes against a real
database. Only Google's token endpoint is replaced (google_auth.exchange_code).
"""

import os
import re
from datetime import datetime, timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from tests.support.dbcase import RealDBTestCase

GOOGLE_ENV = {"GOOGLE_CLIENT_ID": "test-client", "GOOGLE_CLIENT_SECRET": "test-secret",
              "DASHBOARD_URL": "https://loancentral.net"}


class _Author:
    def __init__(self, name, dm_error=None):
        self.name = name
        self.dms = []
        self._dm_error = dm_error

    def message(self, subject=None, message=None):
        if self._dm_error:
            raise self._dm_error
        self.dms.append((subject, message))


class _Comment:
    def __init__(self, body, author, flair=None):
        self.body = body
        self.author = author
        self.author_flair_text = flair
        self.subreddit = type("S", (), {"display_name": "LoanCentral"})()
        self.replies = []

    def reply(self, text):
        self.replies.append(text)


class RedditAccountTests(RealDBTestCase):
    def setUp(self):
        super().setUp()
        import main
        self.main = main
        self.main.command_manager.recent_commands.clear()
        self.main.command_manager.user_command_times.clear()
        self.env = patch.dict(os.environ, GOOGLE_ENV)
        self.env.start()
        self.addCleanup(self.env.stop)
        # The per-IP sign-in limiter is process-wide; every test here is one IP.
        from api import auth
        auth._login_attempts.clear()

    # -- helpers --------------------------------------------------------------

    def dollar_login(self, name, body="$login", **kw):
        self.main.command_manager.recent_commands.clear()
        self.main.command_manager.user_command_times.clear()
        author = _Author(name, dm_error=kw.pop("dm_error", None))
        comment = _Comment(body, author, **kw)
        self.main.command_manager.process_comment(comment)
        return author, comment

    def token_from(self, author):
        match = re.search(r"/account/setup/([\w-]+)", author.dms[-1][1])
        return match.group(1)

    def google(self, token=None, sub="g-1", email="me@gmail.com"):
        """Click "Continue with Google" (or "Sign in with Google") and come back."""
        data = {"setup_token": token} if token else {}
        start = self.client.post("/auth/google/start", data=data)
        self.assertEqual(start.status_code, 302)
        state = parse_qs(urlparse(start.headers["Location"]).query)["state"][0]
        with patch("google_auth.exchange_code", return_value=({"sub": sub, "email": email}, None)):
            return self.client.get(f"/auth/google/callback?state={state}&code=abc")

    def signed_in_as(self):
        with self.client.session_transaction() as s:
            return s.get("username")

    # -- $login ---------------------------------------------------------------

    def test_login_dms_a_setup_link_and_stays_quiet_in_the_thread(self):
        author, comment = self.dollar_login("Borrower1")
        self.assertEqual(len(author.dms), 1)
        self.assertIn("/account/setup/", author.dms[0][1])
        self.assertEqual(comment.replies, [])

    def test_bang_login_works_too(self):
        author, _ = self.dollar_login("Borrower1", body="!login")
        self.assertEqual(len(author.dms), 1)

    def test_login_does_not_fire_logi(self):
        _, comment = self.dollar_login("Borrower1")
        self.assertFalse(any("Lender Snapshot" in r for r in comment.replies))

    def test_an_undeliverable_dm_gets_a_reply_explaining_why(self):
        _, comment = self.dollar_login("Closed", dm_error=RuntimeError("NOT_WHITELISTED_BY_USER_MESSAGE"))
        self.assertEqual(len(comment.replies), 1)
        self.assertIn("couldn't send you a private message", comment.replies[0])

    def test_login_is_rate_limited_per_account(self):
        sent = sum(len(self.dollar_login("Spammed")[0].dms) for _ in range(5))
        self.assertEqual(sent, 3)

    def test_a_flaired_lender_is_recorded_as_a_lender(self):
        self.dollar_login("FlairLender", flair="Verified Lender")
        row = self.query("SELECT role, verified_lender FROM user_roles WHERE username = 'flairlender'")[0]
        self.assertEqual((row[0], bool(row[1])), ("lender", True))

    # -- the setup link -------------------------------------------------------

    def test_the_link_shows_who_it_is_for_and_signs_nobody_in(self):
        token = self.token_from(self.dollar_login("Borrower1")[0])
        page = self.client.get(f"/account/setup/{token}")
        self.assertEqual(page.status_code, 200)
        self.assertIn("u/borrower1", page.get_data(as_text=True))
        self.assertIsNone(self.signed_in_as())

    def test_an_expired_link_is_refused(self):
        token = self.token_from(self.dollar_login("Borrower1")[0])
        self.execute("UPDATE account_setup_links SET expires_at = %s",
                     (datetime.now() - timedelta(minutes=1),))
        self.assertIn("expired", self.client.get(f"/account/setup/{token}").get_data(as_text=True))
        self.google(token)
        self.assertIsNone(self.signed_in_as())

    # -- connecting Google, then signing in -----------------------------------

    def test_connecting_google_creates_the_account_and_signs_in(self):
        token = self.token_from(self.dollar_login("Borrower1")[0])
        self.google(token, sub="g-borrower")
        self.assertEqual(self.signed_in_as(), "borrower1")
        row = self.query("SELECT role, reddit_username, google_sub FROM user_roles "
                         "WHERE username = 'borrower1'")[0]
        self.assertEqual(row, ("borrower", "borrower1", "g-borrower"))

    def test_the_link_works_only_once(self):
        token = self.token_from(self.dollar_login("Borrower1")[0])
        self.google(token, sub="g-1")
        self.client.get("/auth/logout")
        self.google(token, sub="g-attacker")
        self.assertIsNone(self.signed_in_as())

    def test_later_sign_ins_are_just_google(self):
        token = self.token_from(self.dollar_login("Borrower1")[0])
        self.google(token, sub="g-1")
        self.client.get("/auth/logout")
        self.google(sub="g-1")
        self.assertEqual(self.signed_in_as(), "borrower1")

    def test_an_unknown_google_account_is_told_to_use_login(self):
        response = self.google(sub="g-stranger")
        self.assertIsNone(self.signed_in_as())
        page = self.client.get(response.headers["Location"]).get_data(as_text=True)
        self.assertIn("$login", page)

    def test_a_new_login_replaces_a_lost_google_account(self):
        token = self.token_from(self.dollar_login("Borrower1")[0])
        self.google(token, sub="g-old")
        old_browser = self.client
        # They lose the Google account and do $login again, from a new browser.
        self.client = self.web.app.test_client()
        token2 = self.token_from(self.dollar_login("Borrower1")[0])
        self.google(token2, sub="g-new")
        self.assertEqual(self.signed_in_as(), "borrower1")
        # The old Google account no longer signs in...
        self.client.get("/auth/logout")
        self.google(sub="g-old")
        self.assertIsNone(self.signed_in_as())
        # ...and the old browser's session ended on its next request.
        self.assertEqual(old_browser.get("/api/users/me").status_code, 401)

    def test_one_google_account_cannot_serve_two_reddit_accounts(self):
        self.google(self.token_from(self.dollar_login("First")[0]), sub="g-shared")
        self.client.get("/auth/logout")
        self.google(self.token_from(self.dollar_login("Second")[0]), sub="g-shared")
        self.assertIsNone(self.signed_in_as())
        self.assertEqual(self.query("SELECT google_sub FROM user_roles WHERE username = 'second'"), [])

    def test_a_linked_reddit_name_signs_into_the_existing_account(self):
        self.make_user("dashlender", role="lender", verified_lender=True)
        self.execute("UPDATE user_roles SET reddit_username = 'redditlender' WHERE username = 'dashlender'")
        self.google(self.token_from(self.dollar_login("RedditLender")[0]), sub="g-l")
        self.assertEqual(self.signed_in_as(), "dashlender")

    def test_a_cancelled_google_screen_does_not_use_up_the_link(self):
        token = self.token_from(self.dollar_login("Borrower1")[0])
        start = self.client.post("/auth/google/start", data={"setup_token": token})
        state = parse_qs(urlparse(start.headers["Location"]).query)["state"][0]
        self.client.get(f"/auth/google/callback?state={state}&error=access_denied")
        self.google(token, sub="g-1")
        self.assertEqual(self.signed_in_as(), "borrower1")

    def test_a_forged_callback_state_is_refused(self):
        token = self.token_from(self.dollar_login("Borrower1")[0])
        self.client.post("/auth/google/start", data={"setup_token": token})
        with patch("google_auth.exchange_code", return_value=({"sub": "g-x", "email": None}, None)):
            self.client.get("/auth/google/callback?state=wrong&code=abc")
        self.assertIsNone(self.signed_in_as())
