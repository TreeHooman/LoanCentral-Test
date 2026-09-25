"""Breadth-first smoke coverage against a real database.

The audit's core finding was that ~85% of the suite replaced the database
connection with a MagicMock, so SQL was never parsed. That hid two shipped
bugs, and a later probe found that **12 of 30 service functions could not run
on SQLite at all** — PostgreSQL-only INTERVAL, DATE_TRUNC, EXTRACT and casts,
plus two tables missing from the dev schema entirely. Production (Postgres) was
fine; dev, tests and the demo were not, which is why nothing caught it.

These tests are deliberately shallow and wide. They do not check business
rules — other files do that. They check that every query actually executes, so
a dialect gap or a missing column fails here instead of on a dashboard.
"""

import re
from decimal import Decimal

import services
from tests.support.dbcase import RealDBTestCase


class ServiceLayerExecutesTests(RealDBTestCase):
    """Every listed service runs its SQL without erroring."""

    def setUp(self):
        super().setUp()
        self.make_user("lender", role="lender", verified_lender=True)
        self.make_user("borrower", role="borrower")
        self.make_user("mod", role="mod")
        self.loan_id, error = services.create_loan(
            lender="lender", borrower="borrower", amount=Decimal("100.00"),
            currency="USD", thread_url="https://example.com/t",
            repay_amount=Decimal("120.00"), repay_date="2027-01-01")
        self.assertIsNone(error)
        self.request_id, error = services.create_loan_request(
            borrower_username="borrower", requested_amount=Decimal("150.00"))
        self.assertIsNone(error)

    def _calls(self):
        return {
            "get_expanded_metrics": lambda: services.get_expanded_metrics(),
            "get_platform_metrics": lambda: services.get_platform_metrics(),
            "get_request_analytics": lambda: services.get_request_analytics(),
            "get_loan_request_queue": lambda: services.get_loan_request_queue(),
            "run_integrity_checks": lambda: services.run_integrity_checks(),
            "queue_due_reminders": lambda: services.queue_due_reminders(dry_run=True),
            "flag_possible_duplicates": lambda: services.flag_possible_duplicates(dry_run=True),
            "flag_missing_thread_links": lambda: services.flag_missing_thread_links(),
            "flag_unlinked_funded_requests": lambda: services.flag_unlinked_funded_requests(),
            "generate_request_quality_report": lambda: services.generate_request_quality_report(),
            "backfill_requests_from_loans": lambda: services.backfill_requests_from_loans(dry_run=True),
            "expire_old_requests": lambda: services.expire_old_requests(dry_run=True),
            "create_magic_link": lambda: services.create_magic_link("borrower"),
            "create_borrower_otp": lambda: services.create_borrower_otp(
                "borrower", "b@example.com", "email"),
            "get_community_health": lambda: services.get_community_health(),
            "get_analytics_summary": lambda: services.get_analytics_summary(),
            "purge_old_notifications": lambda: services.purge_old_notifications(),
            "get_mod_queue": lambda: services.get_mod_queue(),
            "get_risk_indicators": lambda: services.get_risk_indicators(),
            "get_disputed_loans": lambda: services.get_disputed_loans(),
            "get_audit_investigation_summary": lambda: services.get_audit_investigation_summary("borrower"),
            "get_user_activity_timeline": lambda: services.get_user_activity_timeline("borrower"),
            "get_lender_management_list": lambda: services.get_lender_management_list(),
            "get_borrower_activity_list": lambda: services.get_borrower_activity_list(),
            "global_search": lambda: services.global_search("test"),
            "get_queue_stats": lambda: services.get_queue_stats(),
            "get_lender_stats": lambda: services.get_lender_stats("lender"),
            "get_user_profile": lambda: services.get_user_profile("borrower"),
            "get_active_loans": lambda: services.get_active_loans("borrower"),
            "get_loan_history": lambda: services.get_loan_history("borrower"),
            "get_loan_events": lambda: services.get_loan_events(self.loan_id),
            "get_request_events": lambda: services.get_request_events(self.request_id),
            "get_audit_log": lambda: services.get_audit_log(),
            "get_recent_activity": lambda: services.get_recent_activity(),
            "get_notifications": lambda: services.get_notifications("borrower"),
            "get_notification_preferences": lambda: services.get_notification_preferences("borrower"),
            "list_reddit_actions": lambda: services.list_reddit_actions(),
            "list_banned_users": lambda: services.list_banned_users(),
            "list_lenders": lambda: services.list_lenders(),
            "get_admin_user_profile": lambda: services.get_admin_user_profile("borrower"),
            "list_verification_applications": lambda: services.list_verification_applications(),
            "get_feedback_list": lambda: services.get_feedback_list(),
            "get_announcements": lambda: services.get_announcements(),
            "search_loan_requests": lambda: services.search_loan_requests(),
            "find_duplicate_loan_requests": lambda: services.find_duplicate_loan_requests("borrower"),
            "find_duplicate_open_requests": lambda: services.find_duplicate_open_requests("borrower"),
            "get_open_requests": lambda: services.get_open_requests(),
            "get_loan_requests_for_borrower": lambda: services.get_loan_requests_for_borrower("borrower"),
            "get_notification_queue": lambda: services.get_notification_queue(),
            "get_mod_notes": lambda: services.get_mod_notes("borrower"),
            "get_verified_lender_status": lambda: services.get_verified_lender_status("lender"),
            "get_request_summary": lambda: services.get_request_summary(self.request_id),
            "get_loan_request": lambda: services.get_loan_request(self.request_id),
        }

    #: Text that means the query did not run, as opposed to a business refusal.
    _SQL_ERROR = re.compile(
        r"no such (table|column|function)|syntax error|unrecognized token"
        r"|misuse of|does not exist|undefined", re.I)

    def test_every_listed_service_executes_its_sql(self):
        broken = []
        for name, call in self._calls().items():
            try:
                result = call()
            except Exception as exc:
                broken.append(f"{name}: {type(exc).__name__}: {exc}")
                continue
            for item in (result if isinstance(result, tuple) else (result,)):
                if isinstance(item, str) and self._SQL_ERROR.search(item):
                    broken.append(f"{name}: {item}")
        self.assertEqual(broken, [], "service functions whose SQL did not run:\n"
                                     + "\n".join(broken))

    def test_the_list_has_not_quietly_shrunk(self):
        """Stops this file being defanged by deleting entries."""
        self.assertGreaterEqual(len(self._calls()), 50)


class EveryGetRouteRespondsTests(RealDBTestCase):
    """No GET route may return 500.

    This is the breadth net: a dialect gap or missing column anywhere behind a
    dashboard page surfaces here as a 500, whatever the page is.
    """

    #: Routes needing a side effect, a real token, or an external service.
    SKIP = {
        "/auth/logout",          # ends the session the other checks rely on
        "/auth/reddit",          # OAuth, disabled by SECURITY rule 1
        "/auth/callback",
    }

    def setUp(self):
        super().setUp()
        self.make_user("admin", role="admin")
        self.make_user("lender", role="lender", verified_lender=True)
        self.make_user("borrower", role="borrower")
        self.loan_id, error = services.create_loan(
            lender="lender", borrower="borrower", amount=Decimal("100.00"),
            currency="USD", thread_url="https://example.com/t",
            repay_amount=Decimal("120.00"), repay_date="2027-01-01")
        self.assertIsNone(error)
        self.request_id, _ = services.create_loan_request(
            borrower_username="borrower", requested_amount=Decimal("150.00"))
        self.login("admin", role="admin")

    def _get_routes(self):
        """Concrete GET paths, with URL parameters filled in."""
        substitutions = {
            "loan_id": self.loan_id,
            "request_id": self.request_id,
            "username": "borrower",
            "token": "nonexistent-token",
            "key_id": "1",
            "att_id": "1",
            "action_id": "1",
            "application_id": "1",
            "feedback_id": "1",
            "note_id": "1",
            "announcement_id": "1",
        }
        paths = []
        for rule in self.web.app.url_map.iter_rules():
            if "GET" not in (rule.methods or set()):
                continue
            if rule.rule.startswith("/static"):
                continue
            if rule.rule in self.SKIP:
                continue
            path = rule.rule
            for match in re.findall(r"<([^>]+)>", rule.rule):
                name = match.split(":")[-1]
                value = substitutions.get(name)
                if value is None:
                    path = None
                    break
                path = path.replace(f"<{match}>", str(value))
            if path:
                paths.append(path)
        return sorted(set(paths))

    def test_route_discovery_finds_pages(self):
        self.assertGreater(len(self._get_routes()), 60)

    def test_no_get_route_returns_500(self):
        failures = []
        for path in self._get_routes():
            try:
                response = self.client.get(path)
            except Exception as exc:
                failures.append(f"{path} raised {type(exc).__name__}: {exc}")
                continue
            if response.status_code >= 500:
                body = response.get_data(as_text=True)[:200].replace("\n", " ")
                failures.append(f"{path} -> {response.status_code}: {body}")
        self.assertEqual(failures, [], "GET routes returning 5xx:\n"
                                       + "\n".join(failures))

    def test_no_get_route_returns_500_for_a_lender(self):
        """A lower role must be refused cleanly, never crash."""
        self.login("lender", role="lender")
        failures = []
        for path in self._get_routes():
            response = self.client.get(path)
            if response.status_code >= 500:
                failures.append(f"{path} -> {response.status_code}")
        self.assertEqual(failures, [], "GET routes 5xx-ing for a lender:\n"
                                       + "\n".join(failures))

    def test_no_get_route_returns_500_when_signed_out(self):
        self.logout()
        failures = []
        for path in self._get_routes():
            response = self.client.get(path)
            if response.status_code >= 500:
                failures.append(f"{path} -> {response.status_code}")
        self.assertEqual(failures, [], "GET routes 5xx-ing for anonymous:\n"
                                       + "\n".join(failures))


class SchemaParityTests(RealDBTestCase):
    """Every table a migration creates must also exist in the dev schema.

    Three tables — lender_keys, borrower_otp_sessions, borrower_magic_links —
    existed only in scripts/migrations/*.sql, so Postgres had them and SQLite
    did not. Lender API keys, borrower OTP login and magic links were therefore
    impossible to run or test locally. This fails the build rather than letting
    the next one go unnoticed.
    """

    #: Created by scripts/run_migrations.py itself, not by the app schema.
    NOT_IN_APP_SCHEMA = {"schema_migrations"}

    def _migration_tables(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        tables = set()
        for path in (root / "scripts" / "migrations").glob("*.sql"):
            tables.update(re.findall(
                r"CREATE TABLE IF NOT EXISTS\s+(\w+)",
                path.read_text(encoding="utf-8"), re.I))
        return tables - self.NOT_IN_APP_SCHEMA

    def _sqlite_tables(self):
        return {row[0] for row in self.query(
            "SELECT name FROM sqlite_master WHERE type='table'")}

    def test_migration_tables_exist_in_the_dev_database(self):
        missing = sorted(self._migration_tables() - self._sqlite_tables())
        self.assertEqual(missing, [], "tables a migration creates that the "
                                      "SQLite dev schema does not: " + ", ".join(missing))

    def test_migration_discovery_works(self):
        self.assertGreater(len(self._migration_tables()), 5)


class LoginPageTests(RealDBTestCase):
    """The public login page must be accurate and must not leak configuration.

    With Reddit OAuth off by policy, production showed every visitor "Sign in
    with your Reddit account" plus the names of our environment variables.
    """

    def _render(self, is_dev):
        original = self.web.IS_DEV
        self.web.IS_DEV = is_dev
        try:
            self.logout()
            return self.client.get("/login").get_data(as_text=True)
        finally:
            self.web.IS_DEV = original

    def test_production_login_does_not_name_env_vars(self):
        html = self._render(is_dev=False)
        for secret_name in ("DASHBOARD_CLIENT_ID", "DASHBOARD_CLIENT_SECRET", ".env"):
            self.assertNotIn(secret_name, html)

    def test_production_login_does_not_promise_reddit_sign_in(self):
        html = self._render(is_dev=False)
        self.assertNotIn("Sign in with your Reddit account", html)
        self.assertNotIn("Continue with Reddit", html)

    def test_production_login_offers_the_real_methods(self):
        # Google (once configured), $login for newcomers, and keys as a backup.
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "x", "GOOGLE_CLIENT_SECRET": "y"}):
            html = self._render(is_dev=False)
        self.assertIn("Sign in with Google", html)
        self.assertIn("!login", html)
        self.assertIn("Login with Key", html)

    def test_without_google_configured_there_is_no_dead_google_button(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "", "GOOGLE_CLIENT_SECRET": ""}):
            html = self._render(is_dev=False)
        self.assertNotIn("Sign in with Google", html)


class LoginWithoutGoogleTests(RealDBTestCase):
    """Before Google is configured the key form is the way in: shown, not tucked away."""

    def test_key_form_is_open_until_google_is_configured(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "", "GOOGLE_CLIENT_SECRET": ""}):
            html = self.client.get("/login").get_data(as_text=True)
        self.assertIn('<details class="key-login" open>', html)
        self.assertIn("Sign in with your lender key", html)

    def test_key_form_is_tucked_away_once_google_is_configured(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "x", "GOOGLE_CLIENT_SECRET": "y"}):
            html = self.client.get("/login").get_data(as_text=True)
        self.assertIn('<details class="key-login" >', html)
        self.assertIn("Sign in with a key instead", html)


class WebsiteTests(RealDBTestCase):
    """/ is the public website for everyone; /dashboard sends members to theirs."""

    def test_signed_out_visitors_get_the_website(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("Bot commands", html)
        self.assertIn(">Sign in<", html)

    def test_signed_in_members_see_it_with_a_dashboard_button(self):
        self.make_user("lender1", role="lender", verified_lender=True)
        self.login("lender1", role="lender")
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Go to your dashboard", response.get_data(as_text=True))

    def test_dashboard_routes_by_role(self):
        self.make_user("lender1", role="lender", verified_lender=True)
        self.login("lender1", role="lender")
        self.assertIn("/dashboard/lender", self.client.get("/dashboard").headers["Location"])

    def test_dashboard_signed_out_goes_to_login(self):
        self.assertIn("/login", self.client.get("/dashboard").headers["Location"])

    def test_the_front_page_never_touches_the_database(self):
        from unittest.mock import patch
        import services
        self.logout()
        with patch.object(services, "_get_db", side_effect=AssertionError("DB opened")):
            self.assertEqual(self.client.get("/").status_code, 200)


class NavOnEveryPageTests(RealDBTestCase):
    """Every mod/admin page shows the menu, even when its route passes no role."""

    def test_pages_without_a_role_argument_still_show_the_menu(self):
        self.make_user("boss", role="admin")
        self.login("boss", role="admin")
        for path in ("/dashboard/admin/keys", "/dashboard/admin/audit-log", "/dashboard/admin/search"):
            response = self.client.get(path)
            if response.status_code == 404:
                continue
            html = response.get_data(as_text=True)
            self.assertIn("Bans &amp; Sync", html, path)
            self.assertIn("u/boss", html, path)


class LegalPagesTests(RealDBTestCase):
    def test_terms_say_we_are_not_a_lender(self):
        html = self.client.get("/terms").get_data(as_text=True)
        self.assertIn("record-keeping tool, not a lender", html)
        self.assertIn("does not report to credit bureaus", html)
        self.assertIn("/privacy", html)

    def test_privacy_policy_is_public_and_names_what_we_store(self):
        response = self.client.get("/privacy")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        for fact in ("Google account ID and email address", "90 days", "never your Google password",
                     "no advertising or analytics cookies"):
            self.assertIn(fact, html)

    def test_every_public_page_links_both(self):
        for path in ("/", "/login", "/terms", "/privacy"):
            html = self.client.get(path).get_data(as_text=True)
            self.assertIn("/terms", html, path)
            self.assertIn("/privacy", html, path)
