"""Regression coverage that runs against a real database.

Every test here failed before the fix it guards. They all exist because the
equivalent mocked tests passed while the code was broken — a ``MagicMock``
cursor accepts SQL that no database would.
"""

from datetime import datetime
from decimal import Decimal

import services
from tests.support.dbcase import RealDBTestCase


class UpdateRequestStatusSQLTests(RealDBTestCase):
    """`update_request_status` used Postgres-only ``E'\\n'``, a SQLite syntax error.

    The mocked tests asserted on the return value of a MagicMock cursor, so the
    statement was never parsed and the bug shipped to every dev/demo dashboard.
    """

    def setUp(self):
        super().setUp()
        self.request_id, error = services.create_loan_request(
            borrower_username="borrower",
            thread_url="https://example.com/r1",
            requested_amount=Decimal("150.00"),
        )
        self.assertIsNone(error)

    def test_status_update_executes_when_notes_are_empty(self):
        ok, error = services.update_request_status(
            self.request_id, "expired", actor="mod")
        self.assertIsNone(error)
        self.assertTrue(ok)
        rows = self.query(
            "SELECT request_status FROM loan_requests WHERE request_id = %s",
            (self.request_id,))
        self.assertEqual(rows[0][0], "expired")

    def test_status_update_executes_when_appending_to_existing_notes(self):
        """The second update takes the ELSE branch that concatenates notes."""
        services.update_request_status(self.request_id, "expired", actor="mod", note="first")
        ok, error = services.update_request_status(
            self.request_id, "open", actor="mod", note="second")
        self.assertIsNone(error)
        self.assertTrue(ok)
        notes = self.query(
            "SELECT notes FROM loan_requests WHERE request_id = %s",
            (self.request_id,))[0][0]
        self.assertIn("first", notes)
        self.assertIn("second", notes)
        self.assertIn("\n", notes, "appended notes should be newline-separated")

    def test_unknown_request_is_reported_not_crashed(self):
        ok, error = services.update_request_status("REQ-NOPE", "expired", actor="mod")
        self.assertFalse(ok)
        self.assertEqual(error, "Request not found")


class ReportPaymentSQLTests(RealDBTestCase):
    """`/report-payment` had the same ``E'\\n'`` bug in its notes append."""

    def setUp(self):
        super().setUp()
        self.make_user("lender", role="lender", verified_lender=True)
        self.make_user("borrower", role="borrower")
        self.loan_id, error = services.create_loan(
            lender="lender", borrower="borrower", amount=Decimal("100.00"),
            currency="USD", thread_url="https://example.com/t",
            repay_amount=Decimal("120.00"), repay_date="2027-01-01")
        self.assertIsNone(error)

    def test_first_and_second_report_both_execute(self):
        self.login("borrower", role="borrower")
        first = self.client.post(f"/api/loans/{self.loan_id}/report-payment",
                                 json={"amount": "50.00", "currency": "USD"})
        self.assertEqual(first.status_code, 200, first.get_json())

        # Second report takes the concatenation branch.
        second = self.client.post(f"/api/loans/{self.loan_id}/report-payment",
                                  json={"amount": "70.00", "currency": "USD",
                                        "note": "rest sent"})
        self.assertEqual(second.status_code, 200, second.get_json())

        notes = self.query("SELECT notes FROM loans WHERE loan_id = %s",
                           (self.loan_id,))[0][0]
        self.assertIn("50.00", notes)
        self.assertIn("70.00", notes)
        self.assertIn("rest sent", notes)


class DisputeAuthorizationTests(RealDBTestCase):
    """A logged-in user could dispute anyone's loan by naming them in the body.

    Worse than status vandalism: ``dispute_loan`` writes the audit row with the
    supplied name as the actor, so the log blamed the victim.
    """

    def setUp(self):
        super().setUp()
        self.make_user("lender", role="lender", verified_lender=True)
        self.make_user("victim", role="borrower")
        self.make_user("attacker", role="borrower")
        self.loan_id, error = services.create_loan(
            lender="lender", borrower="victim", amount=Decimal("200.00"),
            currency="USD", thread_url="https://example.com/t2",
            repay_amount=Decimal("240.00"), repay_date="2027-02-01")
        self.assertIsNone(error)

    def _status(self):
        return self.query("SELECT status FROM loans WHERE loan_id = %s",
                          (self.loan_id,))[0][0]

    def test_other_user_cannot_dispute_someone_elses_loan(self):
        self.login("attacker", role="borrower")
        response = self.client.post(f"/api/loans/{self.loan_id}/dispute",
                                    json={"borrower": "victim"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._status(), "confirmed",
                         "an unauthorized dispute must not change loan status")

    def test_other_user_cannot_dispute_by_omitting_the_body(self):
        """Falling back to the session must not match a loan they don't own."""
        self.login("attacker", role="borrower")
        response = self.client.post(f"/api/loans/{self.loan_id}/dispute", json={})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._status(), "confirmed")

    def test_borrower_can_still_dispute_their_own_loan(self):
        self.login("victim", role="borrower")
        response = self.client.post(f"/api/loans/{self.loan_id}/dispute", json={})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self._status(), "disputed")

    def test_dispute_audit_row_names_the_real_actor(self):
        self.login("victim", role="borrower")
        self.client.post(f"/api/loans/{self.loan_id}/dispute", json={})
        actors = [row[0] for row in self.query(
            "SELECT actor_username FROM audit_logs WHERE action_type = 'dispute_opened'")]
        self.assertEqual(actors, ["victim"])


class RequestStateTransitionTests(RealDBTestCase):
    """The state machine from loan_states.py — see AUDIT_2026-09-21.md §3.3.

    Before it existed, update_request_status accepted any status from any
    status, so a funded request could be reopened and funded again.
    """

    def setUp(self):
        super().setUp()
        self.make_user("lender", role="lender", verified_lender=True)
        self.request_id, error = services.create_loan_request(
            borrower_username="borrower",
            thread_url="https://example.com/r2",
            requested_amount=Decimal("150.00"),
        )
        self.assertIsNone(error)

    def _status(self):
        return self.query(
            "SELECT request_status FROM loan_requests WHERE request_id = %s",
            (self.request_id,))[0][0]

    def test_funded_request_cannot_be_reopened(self):
        """The double-funding hole: funded -> open is no longer a legal move."""
        services.update_request_status(self.request_id, "funded", actor="mod")
        ok, error = services.update_request_status(self.request_id, "open", actor="mod")
        self.assertFalse(ok)
        self.assertIn("admin override", error)
        self.assertEqual(self._status(), "funded")

    def test_admin_override_can_correct_a_mistaken_funding(self):
        services.update_request_status(self.request_id, "funded", actor="mod")
        ok, error = services.update_request_status(
            self.request_id, "open", actor="admin", note="funded in error", force=True)
        self.assertIsNone(error)
        self.assertTrue(ok)
        self.assertEqual(self._status(), "open")

    def test_override_is_recorded_in_the_request_note(self):
        services.update_request_status(self.request_id, "funded", actor="mod")
        services.update_request_status(self.request_id, "open", actor="admin", force=True)
        notes = self.query("SELECT notes FROM loan_requests WHERE request_id = %s",
                           (self.request_id,))[0][0]
        self.assertIn("admin override", notes)

    def test_normal_transitions_still_work(self):
        for target in ("expired", "open", "duplicate", "open", "cancelled"):
            ok, error = services.update_request_status(self.request_id, target, actor="mod")
            self.assertTrue(ok, f"{target}: {error}")
        self.assertEqual(self._status(), "cancelled")

    def test_removed_is_terminal(self):
        services.update_request_status(self.request_id, "removed", actor="mod")
        ok, error = services.update_request_status(self.request_id, "open", actor="mod")
        self.assertFalse(ok)
        self.assertEqual(self._status(), "removed")

    def test_invalid_status_is_still_rejected(self):
        ok, error = services.update_request_status(self.request_id, "banana", actor="mod")
        self.assertFalse(ok)
        self.assertIn("Invalid status", error)

    def test_no_op_transition_is_rejected(self):
        ok, error = services.update_request_status(self.request_id, "open", actor="mod")
        self.assertFalse(ok)
        self.assertIn("already open", error)
