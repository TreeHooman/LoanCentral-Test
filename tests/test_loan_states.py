"""Phase 2 — the loan/request lifecycle tables in loan_states.py.

Pure-function tests for the table itself, plus real-database tests proving the
loan mutators actually consult it.
"""

import unittest
from decimal import Decimal

import services
from loan_states import (
    LOAN_STATUSES,
    LOAN_TRANSITIONS,
    MOD_ONLY_LOAN_TRANSITIONS,
    REQUEST_STATUSES,
    REQUEST_TRANSITIONS,
    TERMINAL_LOAN_STATUSES,
    TERMINAL_REQUEST_STATUSES,
    loan_transition_error,
    request_transition_error,
)
from tests.support.dbcase import RealDBTestCase


class TableConsistencyTests(unittest.TestCase):
    """The tables must be internally coherent or the guards are meaningless."""

    def test_every_loan_status_has_a_transition_entry(self):
        self.assertEqual(set(LOAN_TRANSITIONS), set(LOAN_STATUSES))

    def test_every_request_status_has_a_transition_entry(self):
        self.assertEqual(set(REQUEST_TRANSITIONS), set(REQUEST_STATUSES))

    def test_loan_transition_targets_are_all_known_statuses(self):
        for current, targets in LOAN_TRANSITIONS.items():
            self.assertTrue(targets <= LOAN_STATUSES,
                            f"{current} points at unknown statuses")

    def test_request_transition_targets_are_all_known_statuses(self):
        for current, targets in REQUEST_TRANSITIONS.items():
            self.assertTrue(targets <= REQUEST_STATUSES,
                            f"{current} points at unknown statuses")

    def test_terminal_statuses_have_no_outbound_transitions(self):
        for status in TERMINAL_LOAN_STATUSES:
            self.assertEqual(LOAN_TRANSITIONS[status], frozenset())
        for status in TERMINAL_REQUEST_STATUSES:
            self.assertEqual(REQUEST_TRANSITIONS[status], frozenset())

    def test_mod_only_transitions_are_real_transitions(self):
        for current, target in MOD_ONLY_LOAN_TRANSITIONS:
            self.assertIn(target, LOAN_TRANSITIONS[current])

    def test_services_shares_the_request_vocabulary(self):
        self.assertEqual(services._LR_STATUSES, REQUEST_STATUSES)


class LoanTransitionTests(unittest.TestCase):

    def test_closed_loans_cannot_be_changed(self):
        for closed in ("repaid", "refunded"):
            for target in ("unpaid", "partially_repaid", "disputed", "refunded"):
                self.assertIsNotNone(
                    loan_transition_error(closed, target),
                    f"{closed} -> {target} should be blocked")

    def test_a_defaulted_borrower_can_still_pay(self):
        self.assertIsNone(loan_transition_error("unpaid", "partially_repaid"))
        self.assertIsNone(loan_transition_error("unpaid", "repaid"))

    def test_partial_payments_may_repeat(self):
        self.assertIsNone(loan_transition_error("partially_repaid", "partially_repaid"))

    def test_clearing_a_default_is_mod_only(self):
        self.assertIsNotNone(loan_transition_error("unpaid", "confirmed"))
        self.assertIsNotNone(
            loan_transition_error("unpaid", "confirmed", actor_role="lender"))
        self.assertIsNone(
            loan_transition_error("unpaid", "confirmed", actor_role="mod"))
        self.assertIsNone(
            loan_transition_error("unpaid", "confirmed", actor_role="admin"))

    def test_unknown_target_is_rejected(self):
        self.assertIn("Unknown loan status",
                      loan_transition_error("confirmed", "banana"))

    def test_unknown_stored_status_is_refused_not_guessed(self):
        error = loan_transition_error("weird_legacy_value", "repaid")
        self.assertIn("unrecognised status", error)

    def test_status_comparison_ignores_case_and_padding(self):
        self.assertIsNone(loan_transition_error("  CONFIRMED ", "Repaid"))


class RequestTransitionTests(unittest.TestCase):

    def test_funded_is_terminal_without_an_override(self):
        error = request_transition_error("funded", "open")
        self.assertIn("admin override", error)

    def test_override_permits_the_correction(self):
        self.assertIsNone(request_transition_error("funded", "open", force=True))

    def test_override_still_refuses_an_unknown_status(self):
        self.assertIn("Invalid status",
                      request_transition_error("funded", "banana", force=True))

    def test_open_request_can_be_funded(self):
        self.assertIsNone(request_transition_error("open", "funded"))

    def test_wrongly_flagged_duplicate_can_be_reopened(self):
        self.assertIsNone(request_transition_error("duplicate", "open"))

    def test_removed_is_terminal(self):
        self.assertIsNotNone(request_transition_error("removed", "open"))

    def test_no_op_is_reported(self):
        self.assertIn("already open", request_transition_error("open", "open"))


class LoanMutatorsConsultTheTableTests(RealDBTestCase):
    """Proves the guards are wired in, not just defined."""

    def setUp(self):
        super().setUp()
        self.make_user("lender", role="lender", verified_lender=True)
        self.make_user("borrower", role="borrower")
        self.loan_id, error = services.create_loan(
            lender="lender", borrower="borrower", amount=Decimal("100.00"),
            currency="USD", thread_url="https://example.com/t",
            repay_amount=Decimal("100.00"), repay_date="2027-01-01")
        self.assertIsNone(error)

    def _status(self):
        return self.query("SELECT status FROM loans WHERE loan_id = %s",
                          (self.loan_id,))[0][0]

    def test_repaid_loan_rejects_further_payment(self):
        services.mark_repaid(self.loan_id, Decimal("100.00"), "USD", "lender")
        self.assertEqual(self._status(), "repaid")
        result, error = services.mark_repaid(
            self.loan_id, Decimal("10.00"), "USD", "lender")
        self.assertIsNone(result)
        self.assertIsNotNone(error)
        self.assertEqual(self._status(), "repaid")

    def test_repaid_loan_cannot_be_marked_unpaid(self):
        services.mark_repaid(self.loan_id, Decimal("100.00"), "USD", "lender")
        result, error = services.mark_unpaid(self.loan_id, "lender")
        self.assertIsNone(result)
        self.assertEqual(self._status(), "repaid")

    def test_refunded_loan_cannot_be_disputed(self):
        services.mark_refunded_by_id(self.loan_id, "lender")
        self.assertEqual(self._status(), "refunded")
        result, error = services.dispute_loan(self.loan_id, "borrower")
        self.assertIsNone(result)
        self.assertEqual(self._status(), "refunded")

    def test_unpaid_loan_still_accepts_a_payment(self):
        services.mark_unpaid(self.loan_id, "lender")
        self.assertEqual(self._status(), "unpaid")
        result, error = services.mark_repaid(
            self.loan_id, Decimal("100.00"), "USD", "lender")
        self.assertIsNone(error, error)
        self.assertEqual(self._status(), "repaid")

    def test_partial_then_full_payment_walks_the_lifecycle(self):
        services.mark_repaid(self.loan_id, Decimal("40.00"), "USD", "lender")
        self.assertEqual(self._status(), "partially_repaid")
        services.mark_repaid(self.loan_id, Decimal("30.00"), "USD", "lender")
        self.assertEqual(self._status(), "partially_repaid")
        services.mark_repaid(self.loan_id, Decimal("30.00"), "USD", "lender")
        self.assertEqual(self._status(), "repaid")
