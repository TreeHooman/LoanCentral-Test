"""Break-in attempts against the dashboard, as a signed-in attacker would try them.

Each test is one attack with a realistic request body. The assertion is the
defence: the request is refused (or neutralised) and nothing in the database
changed. See also test_url_guessing_realdb.py (every route x every role).
"""

import csv
import io
from decimal import Decimal

import services
from tests.support.dbcase import RealDBTestCase

ORIGIN = {"Origin": "http://localhost"}


class AttackCase(RealDBTestCase):
    def setUp(self):
        super().setUp()
        self.make_user("lendera", role="lender", verified_lender=True)
        self.make_user("lenderb", role="lender", verified_lender=True)
        self.make_user("boba", role="borrower")
        self.make_user("bobb", role="borrower")
        self.make_user("moddy", role="mod")
        self.loan_b = self.new_loan("lenderb", "bobb")      # the victim loan
        self.loan_a = self.new_loan("lendera", "boba")      # the attacker's own

    def new_loan(self, lender, borrower, amount="100"):
        loan_id, error = services.create_loan(
            lender=lender, borrower=borrower, amount=Decimal(amount), currency="USD",
            thread_url="https://reddit.com/r/loancentral/x", repay_amount=Decimal("120"),
            repay_date="2027-01-01")
        self.assertIsNone(error)
        return loan_id

    def loan(self, loan_id):
        row = self.query("SELECT status, amount_repaid, repay_amount, notes, borrower_acknowledged_at "
                         "FROM loans WHERE loan_id = %s", (loan_id,))[0]
        return tuple(row)

    def post(self, url, body=None, method="POST"):
        self.web._api_rate_hits.clear()
        return self.client.open(url, method=method, json=body or {}, headers=ORIGIN)


class LoanTamperingTests(AttackCase):
    """Lender A tries to change lender B's loan, with complete, valid bodies."""

    def test_cannot_touch_another_lenders_loan(self):
        self.login("lendera", role="lender")
        before = self.loan(self.loan_b)
        attempts = [
            ("POST", f"/api/loans/{self.loan_b}/paid", {"amount": "120", "currency": "USD"}),
            ("POST", f"/api/loans/{self.loan_b}/unpaid", {}),
            ("POST", f"/api/loans/{self.loan_b}/refunded", {}),
            ("PUT", f"/api/loans/{self.loan_b}/terms", {"repay_amount": "1", "repay_date": "2027-01-01"}),
            ("POST", f"/api/loans/{self.loan_b}/notes", {"note": "pwned"}),
            ("POST", "/api/loans/bulk-paid", {"loan_ids": [self.loan_b], "loans": [self.loan_b]}),
        ]
        for method, url, body in attempts:
            r = self.post(url, body, method)
            if url.endswith("bulk-paid"):    # 207 = per-loan results; this one must be an error
                self.assertFalse(r.get_json().get("updated"), "bulk-paid updated another lender's loan")
                continue
            self.assertGreaterEqual(r.status_code, 400, f"{method} {url} was accepted")
        self.assertEqual(self.loan(self.loan_b), before)

    def test_cannot_act_as_another_lender(self):
        self.login("lendera", role="lender")
        for url, body in ((f"/api/loans/{self.loan_b}/paid",
                           {"lender": "lenderb", "amount": "120", "currency": "USD"}),
                          (f"/api/loans/{self.loan_b}/unpaid", {"lender": "lenderb"}),
                          ("/api/loans/create", {"lender": "lenderb", "borrower": "boba", "amount": "5",
                                                 "currency": "USD"})):
            self.assertEqual(self.post(url, body).status_code, 403, url)
        self.assertEqual(self.loan(self.loan_b)[0], "confirmed")

    def test_borrower_cannot_use_lender_actions(self):
        self.login("bobb", role="borrower")
        for url, body in ((f"/api/loans/{self.loan_b}/paid", {"amount": "120", "currency": "USD"}),
                          (f"/api/loans/{self.loan_b}/refunded", {}),
                          ("/api/loans/create", {"borrower": "boba", "amount": "5", "currency": "USD"})):
            self.assertEqual(self.post(url, body).status_code, 403, url)
        self.assertEqual(self.loan(self.loan_b)[0], "confirmed")

    def test_a_forged_role_in_the_session_is_not_trusted_for_lender_writes(self):
        """Even a session claiming 'lender' is checked against the database."""
        self.login("boba", role="lender")          # boba is a borrower in the DB
        r = self.post("/api/loans/create", {"borrower": "bobb", "amount": "5", "currency": "USD"})
        self.assertEqual(r.status_code, 403)

    def test_borrower_cannot_acknowledge_or_report_on_someone_elses_loan(self):
        self.login("boba", role="borrower")
        before = self.loan(self.loan_b)
        for url, body in ((f"/api/loans/{self.loan_b}/acknowledge", {"note": "x"}),
                          (f"/api/loans/{self.loan_b}/report-payment",
                           {"amount": "120", "currency": "USD", "note": "paid"})):
            self.assertGreaterEqual(self.post(url, body).status_code, 400, url)
        self.assertEqual(self.loan(self.loan_b), before)


class MoneyInputTests(AttackCase):
    def test_bad_amounts_are_refused(self):
        self.login("lendera", role="lender")
        for amount in ("-5", "0", "NaN", "Infinity", "1e400", "0.001", "abc", True, [], {"a": 1},
                       "99999999999999"):
            r = self.post(f"/api/loans/{self.loan_a}/paid", {"amount": amount, "currency": "USD"})
            self.assertGreaterEqual(r.status_code, 400, repr(amount))
            r = self.post("/api/loans/create", {"borrower": "bobb", "amount": amount, "currency": "USD"})
            self.assertGreaterEqual(r.status_code, 400, repr(amount))
        self.assertEqual(self.loan(self.loan_a)[1], 0)

    def test_overpaying_does_not_push_repaid_past_the_amount_due(self):
        self.login("lendera", role="lender")
        self.post(f"/api/loans/{self.loan_a}/paid", {"amount": "5000", "currency": "USD"})
        status, repaid, due, _, _ = self.loan(self.loan_a)
        self.assertLessEqual(Decimal(str(repaid)), Decimal(str(due)))


class RankFarmingTests(AttackCase):
    def test_cannot_lend_to_yourself_under_your_other_name(self):
        """A lender's Reddit name and dashboard name are the same person."""
        self.execute("UPDATE user_roles SET reddit_username = 'lendera_reddit' WHERE username = 'lendera'")
        self.login("lendera", role="lender")
        for borrower in ("lendera", "LENDERA", "lendera_reddit", " lendera "):
            r = self.post("/api/loans/create", {"borrower": borrower, "amount": "5", "currency": "USD"})
            self.assertGreaterEqual(r.status_code, 400, borrower)
        count = self.query("SELECT count(*) FROM loans WHERE lender = 'lendera'")[0][0]
        self.assertEqual(count, 1)


class EscalationTests(AttackCase):
    def test_role_fields_in_bodies_are_ignored(self):
        self.login("boba", role="borrower")
        self.post("/api/verification/apply", {"requested_role": "admin", "role": "admin"})
        self.post("/api/admin/roles/boba", {"role": "admin"})
        self.post("/api/notifications/preferences", {"role": "admin", "username": "moddy"}, method="PUT")
        role = self.query("SELECT role FROM user_roles WHERE username = 'boba'")[0][0]
        self.assertEqual(role, "borrower")
        pending = self.query("SELECT requested_role FROM verification_applications WHERE username = 'boba'")
        for (requested,) in pending:
            self.assertEqual(requested, "lender")

    def test_forged_session_cookie_is_ignored(self):
        """A cookie signed with any other secret is not a session."""
        from flask.sessions import SecureCookieSessionInterface
        from flask import Flask
        evil = Flask("evil")
        evil.secret_key = "guessed-secret"
        cookie = SecureCookieSessionInterface().get_signing_serializer(evil).dumps(
            {"username": "moddy", "role": "admin"})
        self.logout()
        self.client.set_cookie("session", cookie, domain="localhost")
        r = self.client.get("/api/admin/roles")
        self.assertIn(r.status_code, (401, 403))

    def test_feedback_cannot_be_filed_as_someone_else(self):
        self.login("boba", role="borrower")
        self.post("/api/feedback", {"category": "bug", "title": "t", "description": "d",
                                    "username": "moddy"})
        names = [r[0] for r in self.query("SELECT username FROM feedback_submissions")]
        self.assertNotIn("moddy", names)

    def test_cannot_read_other_peoples_notifications(self):
        services.create_notification("bobb", "x", "secret", "bobb only")
        self.login("boba", role="borrower")
        body = self.client.get("/api/notifications").get_data(as_text=True)
        self.assertNotIn("bobb only", body)
        ids = [r[0] for r in self.query("SELECT id FROM notifications WHERE username = 'bobb'")]
        self.post("/api/notifications/read", {"ids": ids})
        unread = self.query("SELECT count(*) FROM notifications WHERE username = 'bobb' AND "
                            "read = FALSE")[0][0] if ids else 0
        self.assertEqual(unread, len(ids))


class InjectionTests(AttackCase):
    SQLI = ["' OR '1'='1", "1; DROP TABLE loans;--", "\" OR 1=1 --", "%' OR 1=1 --",
            "1 UNION SELECT username, role FROM user_roles--"]

    def test_sql_injection_in_query_strings(self):
        self.login("boss", role="admin")
        self.make_user("boss", role="admin")
        for payload in self.SQLI:
            for url in (f"/api/loans?search={payload}", f"/api/loans?status={payload}",
                        f"/api/admin/search?q={payload}", f"/api/loan-requests/search?q={payload}",
                        f"/api/admin/audit-log?action_type={payload}",
                        f"/api/loans?limit={payload}"):
                r = self.client.get(url)
                self.assertLess(r.status_code, 500, url)
        self.login("boba", role="borrower")
        for payload in self.SQLI:
            r = self.client.get(f"/api/loans?search={payload}")
            body = r.get_data(as_text=True)
            self.assertNotIn("bobb", body, "a borrower's search leaked another user's loans")
        self.assertEqual(self.query("SELECT count(*) FROM loans")[0][0], 2)

    def test_sql_injection_in_path_parameters(self):
        self.login("lendera", role="lender")
        for payload in ("1 OR 1=1", "' OR '1'='1", f"{self.loan_b}' --"):
            self.client.get(f"/api/loans/{payload}")
            self.post(f"/api/loans/{payload}/notes", {"note": "x"})
        self.assertEqual(self.loan(self.loan_b)[3], None)

    def test_reflected_script_in_the_address_bar_is_escaped(self):
        marker = "<script>alert(1)</script>"
        self.login("boss", role="admin")
        self.make_user("boss", role="admin")
        for url in (f"/dashboard/admin/search?q={marker}", f"/dashboard/mod?tab={marker}",
                    f"/login?error={marker}", f"/login?next={marker}", f"/{marker}",
                    f"/dashboard/users/{marker}", f"/dashboard/requests/{marker}"):
            body = self.client.get(url).get_data(as_text=True)
            self.assertNotIn(marker, body, url)

    def test_huge_limits_are_capped(self):
        self.login("boss", role="admin")
        self.make_user("boss", role="admin")
        for url in ("/api/loans?limit=100000000", "/api/admin/audit-log?limit=100000000",
                    "/api/notifications?limit=100000000"):
            self.assertLess(self.client.get(url).status_code, 500, url)


class ExportTests(AttackCase):
    def test_csv_export_neutralises_spreadsheet_formulas(self):
        """A note like =HYPERLINK(...) must not run as a formula in Excel."""
        self.execute("UPDATE loans SET notes = %s WHERE loan_id = %s",
                     ('=HYPERLINK("http://evil.example","click")', self.loan_a))
        self.login("lendera", role="lender")
        r = self.client.get("/api/loans/export.csv?lender=lendera")
        self.assertEqual(r.status_code, 200)
        for row in csv.reader(io.StringIO(r.get_data(as_text=True))):
            for cell in row:
                self.assertFalse(cell[:1] in ("=", "+", "-", "@") and not cell[1:2].isdigit(),
                                 f"formula-looking cell exported as-is: {cell!r}")

    def test_cannot_export_someone_elses_loans(self):
        self.login("lendera", role="lender")
        for q in ("lender=lenderb", "borrower=bobb", "lender=LENDERB", "lender=lendera&borrower=bobb"):
            r = self.client.get(f"/api/loans/export.csv?{q}")
            self.assertNotIn("bobb", r.get_data(as_text=True), q)


class AttachmentTests(AttackCase):
    def test_path_tricks_in_attachment_download(self):
        self.login("lendera", role="lender")
        for att in ("..%2F..%2Fapi%2Fapp.py", "1%2F..%2F..%2F.env"):
            r = self.client.get(f"/api/loans/{self.loan_a}/attachments/{att}/download")
            self.assertIn(r.status_code, (400, 403, 404, 405))
            self.assertNotIn("SECRET", r.get_data(as_text=True))


class SelfFundingTests(AttackCase):
    def test_cannot_fund_your_own_request_under_your_other_name(self):
        """Dashboard name 'lendera', Reddit name 'lendera_reddit' posts a [REQ];
        funding it from the dashboard would be a loan to yourself (rank farming)."""
        self.execute("UPDATE user_roles SET reddit_username = 'lendera_reddit' WHERE username = 'lendera'")
        self.execute("INSERT INTO loan_requests (request_id, borrower_username, reddit_post_id, "
                     "requested_amount, request_status) VALUES ('REQ-SELF1', 'lendera_reddit', 'p1', 50, 'open')")
        loan_id, error = services.create_loan(
            lender="lendera", borrower="lendera_reddit", amount=Decimal("50"), currency="USD",
            thread_url="", request_id="REQ-SELF1")
        self.assertIsNone(loan_id)
        self.assertTrue(error)


class BotCommandAttackTests(AttackCase):
    """Malicious Reddit comments, run through the real command handlers."""

    def comment(self, author, body, flair=None, post_author="someone"):
        from unittest.mock import MagicMock
        c = MagicMock()
        c.author.name = author
        c.body = body
        c.author_flair_text = flair
        c.author_flair_template_id = None
        c.submission.author.name = post_author
        c.submission.permalink = "/r/loancentral/comments/abc/x/"
        c.subreddit.display_name = "loancentral"
        return c

    def replies(self, c):
        return " ".join(str(call.args[0]) for call in c.reply.call_args_list)

    def test_lender_commands_ignore_people_without_the_flair(self):
        from commands.loan_command import process_loan_command
        from commands.paid_command import process_paid_command
        c = self.comment("boba", f"$paid_with_id {self.loan_b} 120 USD", flair="Verified Lender · pending")
        process_paid_command(c)
        c = self.comment("boba", "$loan 50 USD u/bobb", flair="Borrower")
        process_loan_command(c)
        self.assertEqual(self.loan(self.loan_b)[1], 0)
        self.assertEqual(self.query("SELECT count(*) FROM loan_offers")[0][0], 0)

    def test_flaired_lender_cannot_pay_off_another_lenders_loan(self):
        from commands.paid_command import process_paid_command
        c = self.comment("lendera", f"$paid_with_id {self.loan_b} 120 USD", flair="Verified Lender")
        process_paid_command(c)
        self.assertEqual(self.loan(self.loan_b)[1], 0)

    def test_offers_to_yourself_and_absurd_amounts_are_refused(self):
        from commands.loan_command import process_loan_command
        for body in ("$loan 50 USD u/lendera", "$loan 999999999999 USD u/bobb"):
            process_loan_command(self.comment("lendera", body, flair="Verified Lender"))
        self.assertEqual(self.query("SELECT count(*) FROM loan_offers")[0][0], 0)

    def test_nobody_else_can_confirm_an_offer(self):
        from commands.confirm_command import process_confirm_command
        from commands.loan_command import process_loan_command
        process_loan_command(self.comment("lendera", "$loan 50 USD u/bobb", flair="Verified Lender"))
        self.assertEqual(self.query("SELECT count(*) FROM loan_offers")[0][0], 1)
        for attacker in ("boba", "lenderb", "lendera"):
            process_confirm_command(self.comment(attacker, "$confirm u/lendera 50 USD"))
        loans = self.query("SELECT count(*) FROM loans WHERE lender = 'lendera' AND borrower = 'bobb'")[0][0]
        self.assertEqual(loans, 0)

    def test_links_in_a_comment_are_not_echoed_into_bot_replies(self):
        from commands.loan_command import process_loan_command
        from commands.logi_command import process_logi_command
        evil = "[click here](https://evil.example)"
        c = self.comment("lendera", f"$loan 50 USD u/bobb {evil}", flair="Verified Lender")
        process_loan_command(c)
        self.assertNotIn("evil.example", self.replies(c))
        c = self.comment("boba", f"$logi u/{evil}")
        process_logi_command(c)
        self.assertNotIn("evil.example", self.replies(c))


class KeyGuessingTests(AttackCase):
    def test_guessing_keys_is_rate_limited(self):
        self.web._otp_attempts.clear()
        self.logout()
        codes = [self.client.post("/auth/key", headers={**ORIGIN, "X-API-Key": f"LC-guess-{i}"}).status_code
                 for i in range(30)]
        self.assertIn(429, codes, "30 wrong keys in a row were never slowed down")
        self.assertNotIn(200, codes)
        self.web._otp_attempts.clear()

    def test_a_huge_key_is_refused_cleanly(self):
        self.web._otp_attempts.clear()
        r = self.client.post("/auth/key", headers={**ORIGIN, "X-API-Key": "A" * 100000})
        self.assertIn(r.status_code, (400, 401, 413, 431))
        self.web._otp_attempts.clear()
