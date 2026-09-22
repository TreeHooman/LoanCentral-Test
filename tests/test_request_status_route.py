"""The request status route: transition rules and the admin-only override."""

import services
from tests.support.dbcase import RealDBTestCase


class RequestStatusRouteTests(RealDBTestCase):

    def setUp(self):
        super().setUp()
        self.make_user("mod", role="mod")
        self.make_user("admin", role="admin")
        self.request_id, error = services.create_loan_request(
            borrower_username="borrower", requested_amount="150.00")
        self.assertIsNone(error)

    def _patch(self, status, **body):
        body["status"] = status
        return self.client.patch(f"/api/loan-requests/{self.request_id}/status", json=body)

    def _status(self):
        return self.query(
            "SELECT request_status FROM loan_requests WHERE request_id = %s",
            (self.request_id,))[0][0]

    def test_mod_can_make_a_legal_transition(self):
        self.login("mod", role="mod")
        response = self._patch("expired")
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self._status(), "expired")

    def test_mod_cannot_reopen_a_funded_request(self):
        self.login("mod", role="mod")
        self._patch("funded")
        response = self._patch("open")
        self.assertEqual(response.status_code, 400)
        self.assertIn("admin override", response.get_json()["error"])
        self.assertEqual(self._status(), "funded")

    def test_mod_cannot_use_the_override(self):
        self.login("mod", role="mod")
        self._patch("funded")
        response = self._patch("open", force=True)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._status(), "funded")

    def test_admin_can_use_the_override(self):
        self.login("admin", role="admin")
        self._patch("funded")
        response = self._patch("open", force=True)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self._status(), "open")

    def test_override_is_audited_as_forced(self):
        self.login("admin", role="admin")
        self._patch("funded")
        self._patch("open", force=True)
        rows = self.query(
            "SELECT new_value_json FROM audit_logs "
            "WHERE action_type = 'request_status_updated' ORDER BY id DESC")
        self.assertIn('"forced": true', rows[0][0])

    def test_borrower_cannot_change_a_request_status(self):
        self.login("borrower", role="borrower")
        response = self._patch("removed")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._status(), "open")

    def test_anonymous_cannot_change_a_request_status(self):
        self.logout()
        response = self._patch("removed")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._status(), "open")

    def test_unknown_status_is_rejected(self):
        self.login("mod", role="mod")
        response = self._patch("banana")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._status(), "open")
