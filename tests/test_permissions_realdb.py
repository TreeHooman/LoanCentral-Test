"""Phase 4 — server-side permission enforcement.

The brief asks that write actions be checked server-side and not rely on the
frontend hiding buttons. These tests call the endpoints directly with the wrong
role, against a real database, and assert both the status code and that nothing
changed.

The last class is structural: it reads api/app.py and fails if a write route
ships without a recognised permission gate, so a future route cannot repeat the
dispute-impersonation bug by omission.
"""

import pathlib
import re
import unittest
from decimal import Decimal

import services
from tests.support.dbcase import RealDBTestCase


class LenderActionPermissionTests(RealDBTestCase):
    """Every lender write is gated on verified-lender status, checked fresh."""

    def setUp(self):
        super().setUp()
        self.make_user("lender", role="lender", verified_lender=True)
        self.make_user("other_lender", role="lender", verified_lender=True)
        self.make_user("unverified", role="lender", verified_lender=False)
        self.make_user("borrower", role="borrower")
        self.loan_id, error = services.create_loan(
            lender="lender", borrower="borrower", amount=Decimal("100.00"),
            currency="USD", thread_url="https://example.com/t",
            repay_amount=Decimal("120.00"), repay_date="2027-01-01")
        self.assertIsNone(error)

    def _status(self):
        return self.query("SELECT status FROM loans WHERE loan_id = %s",
                          (self.loan_id,))[0][0]

    def _loan_count(self):
        return self.query("SELECT COUNT(*) FROM loans")[0][0]

    # -- unverified lenders -------------------------------------------------

    def test_unverified_lender_cannot_create_a_loan(self):
        self.login("unverified", role="lender")
        before = self._loan_count()
        response = self.client.post("/api/loans/create", json={
            "borrower": "borrower", "amount": "50.00", "currency": "USD",
            "repay_amount": "60.00", "repay_date": "2027-06-01"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._loan_count(), before)

    def test_unverified_lender_cannot_record_a_payment(self):
        self.login("unverified", role="lender")
        response = self.client.post(f"/api/loans/{self.loan_id}/paid",
                                    json={"amount": "10.00", "currency": "USD"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._status(), "confirmed")

    def test_unverified_lender_cannot_mark_unpaid(self):
        self.login("unverified", role="lender")
        response = self.client.post(f"/api/loans/{self.loan_id}/unpaid", json={})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._status(), "confirmed")

    def test_unverified_lender_cannot_mark_refunded(self):
        self.login("unverified", role="lender")
        response = self.client.post(f"/api/loans/{self.loan_id}/refunded", json={})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._status(), "confirmed")

    # -- borrowers ----------------------------------------------------------

    def test_borrower_cannot_perform_lender_actions(self):
        self.login("borrower", role="borrower")
        for path, body in (
            (f"/api/loans/{self.loan_id}/paid", {"amount": "10.00", "currency": "USD"}),
            (f"/api/loans/{self.loan_id}/unpaid", {}),
            (f"/api/loans/{self.loan_id}/refunded", {}),
            ("/api/loans/create", {"borrower": "x", "amount": "5.00"}),
        ):
            response = self.client.post(path, json=body)
            self.assertEqual(response.status_code, 403, f"{path} was not refused")
        self.assertEqual(self._status(), "confirmed")

    # -- acting as somebody else -------------------------------------------

    def test_a_lender_cannot_act_as_another_lender(self):
        self.login("other_lender", role="lender")
        response = self.client.post(f"/api/loans/{self.loan_id}/paid",
                                    json={"amount": "10.00", "currency": "USD",
                                          "lender": "lender"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._status(), "confirmed")

    def test_a_verified_lender_cannot_touch_someone_elses_loan(self):
        """Verified, acting as themselves, but not this loan's lender."""
        self.login("other_lender", role="lender")
        response = self.client.post(f"/api/loans/{self.loan_id}/unpaid", json={})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._status(), "confirmed")

    # -- revocation ---------------------------------------------------------

    def test_revoking_verification_takes_effect_on_the_next_write(self):
        self.login("lender", role="lender")
        ok = self.client.post(f"/api/loans/{self.loan_id}/paid",
                              json={"amount": "10.00", "currency": "USD"})
        self.assertEqual(ok.status_code, 200, ok.get_json())

        services.set_verified_lender("lender", False, "admin", "revoked for test")

        after = self.client.post(f"/api/loans/{self.loan_id}/paid",
                                 json={"amount": "10.00", "currency": "USD"})
        self.assertEqual(after.status_code, 403,
                         "a revoked lender must be refused without re-login")

    def test_anonymous_callers_are_refused(self):
        self.logout()
        for path in (f"/api/loans/{self.loan_id}/paid",
                     f"/api/loans/{self.loan_id}/unpaid",
                     "/api/loans/create"):
            response = self.client.post(path, json={})
            self.assertIn(response.status_code, (401, 403), path)


class RoleScopedRoutePermissionTests(RealDBTestCase):
    """Mod-only and admin-only endpoints refuse lower roles."""

    def setUp(self):
        super().setUp()
        self.make_user("lender", role="lender", verified_lender=True)
        self.make_user("mod", role="mod")
        self.make_user("admin", role="admin")

    def test_lender_cannot_reach_mod_endpoints(self):
        self.login("lender", role="lender")
        for path in ("/api/requests", "/api/activity", "/api/verification",
                     "/api/admin/audit-log", "/api/mod/queue", "/api/mod/risk"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 403, path)

    def test_mod_cannot_reach_admin_endpoints(self):
        self.login("mod", role="mod")
        for path in ("/api/admin/metrics", "/api/admin/lenders",
                     "/api/admin/analytics", "/api/admin/request-analytics"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 403, path)

    def test_borrower_cannot_reach_mod_endpoints(self):
        self.login("borrower", role="borrower")
        for path in ("/api/requests", "/api/admin/audit-log"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 403, path)

    def test_admin_can_reach_admin_endpoints(self):
        self.login("admin", role="admin")
        response = self.client.get("/api/admin/metrics")
        self.assertEqual(response.status_code, 200, response.get_json())


class SelfServiceScopingTests(RealDBTestCase):
    """Self-service writes act on the caller, never on a name from the body."""

    def setUp(self):
        super().setUp()
        self.make_user("alice", role="borrower")
        self.make_user("bob", role="borrower")

    def test_verification_application_cannot_be_filed_for_someone_else(self):
        self.login("alice", role="borrower")
        response = self.client.post("/api/verification/apply",
                                    json={"username": "bob", "requested_role": "lender"})
        self.assertEqual(response.status_code, 403)
        rows = self.query(
            "SELECT COUNT(*) FROM verification_applications WHERE lower(username) = 'bob'")
        self.assertEqual(rows[0][0], 0)

    def test_verification_application_for_self_is_allowed(self):
        self.login("alice", role="borrower")
        response = self.client.post("/api/verification/apply",
                                    json={"requested_role": "lender"})
        self.assertEqual(response.status_code, 200, response.get_json())

    def test_notification_preferences_are_scoped_to_the_caller(self):
        self.login("alice", role="borrower")
        response = self.client.put("/api/notifications/preferences",
                                   json={"username": "bob", "due_date_reminders": False})
        self.assertEqual(response.status_code, 200)
        prefs, _ = services.get_notification_preferences("bob")
        self.assertTrue(prefs["due_date_reminders"],
                        "bob's preferences must be untouched")


class EveryWriteRouteHasAGateTests(unittest.TestCase):
    """Structural guard: a new write route cannot ship without a check.

    The dispute-impersonation bug existed because one route among forty was
    missing its inline check. This reads the source and fails on the next one.
    """

    #: Routes that are deliberately open or self-scoped, with the reason.
    EXEMPT = {
        "auth_key":            "login endpoint",
        "api_borrower_claim":  "pre-auth OTP request, rate limited per IP",
        "api_borrower_verify": "pre-auth OTP verification",
        "api_submit_feedback": "self-service, writes session['username'] only",
        "api_update_notif_prefs": "self-service, writes session['username'] only",
        "apply_verification":  "self-service, body username must equal the session",
    }

    GATES = (
        "_lender_write_actor", "_is_mod_or_admin", "_is_admin",
        "_is_lender_verified_fresh", "_private_loan_access",
        "_can_view_user_profile", "account_aliases",
        'session.get("role")', 'session["username"]', "session['username']",
        "if not IS_DEV",
        "@require_mod_api", "@require_admin_api", "@role_required",
        "@verified_lender_required", "@admin_required", "@mod_required",
    )
    WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    def _routes(self):
        src = pathlib.Path(__file__).resolve().parents[1] / "api" / "app.py"
        lines = src.read_text(encoding="utf-8").splitlines()
        routes, i = [], 0
        while i < len(lines):
            if lines[i].startswith("@app.route("):
                match = re.search(
                    r'@app\.route\("([^"]+)"(?:,\s*methods=\[([^\]]*)\])?', lines[i])
                path = match.group(1)
                methods = ["GET"]
                if match.group(2):
                    methods = [m.strip().strip('"\'') for m in match.group(2).split(",")]
                i += 1
                decorators = []
                while i < len(lines) and lines[i].startswith("@"):
                    decorators.append(lines[i].strip())
                    i += 1
                if i < len(lines) and lines[i].startswith("def "):
                    name = lines[i][4:lines[i].index("(")]
                    i += 1
                    body = []
                    while i < len(lines) and (lines[i].startswith((" ", "\t"))
                                              or not lines[i].strip()):
                        body.append(lines[i])
                        i += 1
                    routes.append((path, methods, name,
                                   "\n".join(decorators + body)))
                    continue
            i += 1
        return routes

    def test_source_scan_finds_the_routes(self):
        self.assertGreater(len(self._routes()), 100)

    def test_every_write_route_is_gated(self):
        ungated = []
        for path, methods, name, text in self._routes():
            if not self.WRITE_METHODS & set(methods):
                continue
            if name in self.EXEMPT:
                continue
            if not any(gate in text for gate in self.GATES):
                ungated.append(f"{'/'.join(methods)} {path} ({name})")
        self.assertEqual(ungated, [], "write routes with no permission gate: "
                                      + ", ".join(ungated))

    def test_exemptions_still_exist(self):
        """Stops the allowlist rotting into a blanket exemption."""
        names = {name for _, _, name, _ in self._routes()}
        for exempt in self.EXEMPT:
            self.assertIn(exempt, names,
                          f"{exempt} is exempted but no longer exists — drop it")


class NotificationScopingTests(RealDBTestCase):
    """Marking notifications read must not reach another user's rows.

    Also covers the SQL itself: the previous `id=ANY(%s)` is Postgres-only and
    could not run on SQLite at all.
    """

    def setUp(self):
        super().setUp()
        self.make_user("alice", role="borrower")
        self.make_user("bob", role="borrower")
        services.create_notification("alice", "test", "A", "for alice")
        services.create_notification("bob", "test", "B", "for bob")

    def _unread(self, username):
        return self.query(
            "SELECT COUNT(*) FROM notifications "
            "WHERE lower(username) = %s AND read = FALSE", (username,))[0][0]

    def test_marking_specific_ids_executes(self):
        rows = self.query(
            "SELECT id FROM notifications WHERE lower(username) = 'alice'")
        self.login("alice", role="borrower")
        response = self.client.post("/api/notifications/read",
                                    json={"ids": [rows[0][0]]})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self._unread("alice"), 0)

    def test_cannot_mark_another_users_notification_read(self):
        bob_id = self.query(
            "SELECT id FROM notifications WHERE lower(username) = 'bob'")[0][0]
        self.login("alice", role="borrower")
        response = self.client.post("/api/notifications/read", json={"ids": [bob_id]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._unread("bob"), 1, "bob's notification must stay unread")

    def test_marking_all_only_affects_the_caller(self):
        self.login("alice", role="borrower")
        self.client.post("/api/notifications/read", json={})
        self.assertEqual(self._unread("alice"), 0)
        self.assertEqual(self._unread("bob"), 1)
