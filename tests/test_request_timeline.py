"""Phase 3 — the request timeline is produced by the service layer.

log_request_event used to be called only from api/app.py. Requests the bot
imported had no timeline at all, and funding — the single most important event
on a request — produced no entry whichever interface performed it.

These tests assert on the contents of request_events after each operation, so
they hold regardless of which layer does the writing.
"""

from datetime import datetime
from decimal import Decimal

import services
from tests.support.dbcase import RealDBTestCase


class RequestTimelineTests(RealDBTestCase):

    TITLE = "[REQ] ($150) (#Denver, CO, USA) (Repay $180) (2027-05-01)"

    def setUp(self):
        super().setUp()
        self.make_user("lender", role="lender", verified_lender=True)
        self.make_user("mod", role="mod")

    def events(self, request_id):
        return [(row[0], row[1]) for row in self.query(
            "SELECT event_type, actor FROM request_events "
            "WHERE request_id = %s ORDER BY id", (request_id,))]

    def event_types(self, request_id):
        return [event_type for event_type, _ in self.events(request_id)]

    # -- creation -----------------------------------------------------------

    def test_bot_import_creates_a_timeline_entry(self):
        request_id, error = services.save_loan_request(
            "borrower", self.TITLE, "https://example.com/p", datetime.now(), "post1")
        self.assertIsNone(error)
        self.assertEqual(self.event_types(request_id), ["created"])

    def test_dashboard_creation_creates_a_timeline_entry(self):
        request_id, error = services.create_loan_request(
            borrower_username="borrower", requested_amount=Decimal("150.00"))
        self.assertIsNone(error)
        self.assertEqual(self.event_types(request_id), ["created"])

    def test_reimport_does_not_duplicate_the_created_event(self):
        first, _ = services.save_loan_request(
            "borrower", self.TITLE, "https://example.com/p", datetime.now(), "post2")
        services.save_loan_request(
            "borrower", self.TITLE, "https://example.com/p", datetime.now(), "post2")
        self.assertEqual(self.event_types(first), ["created"])

    # -- funding ------------------------------------------------------------

    def test_funding_through_the_service_records_the_lender(self):
        request_id, _ = services.save_loan_request(
            "borrower", self.TITLE, "https://example.com/p", datetime.now(), "post3")
        loan_id, error = services.fund_loan_request(
            request_id, "lender", 180.0, "2027-05-01")
        self.assertIsNone(error, error)

        self.assertEqual(self.event_types(request_id), ["created", "funded"])
        funded = [e for e in self.events(request_id) if e[0] == "funded"][0]
        self.assertEqual(funded[1], "lender")

    def test_funded_event_names_the_lender_and_loan(self):
        request_id, _ = services.save_loan_request(
            "borrower", self.TITLE, "https://example.com/p", datetime.now(), "post4")
        loan_id, _ = services.fund_loan_request(request_id, "lender", 180.0, "2027-05-01")
        note = self.query(
            "SELECT note FROM request_events WHERE request_id = %s AND event_type = 'funded'",
            (request_id,))[0][0]
        self.assertIn("u/lender", note)
        self.assertIn(loan_id, note)

    def test_funding_through_the_dashboard_route_records_the_same_event(self):
        request_id, _ = services.save_loan_request(
            "borrower", self.TITLE, "https://example.com/p", datetime.now(), "post5")
        self.login("lender", role="lender")
        response = self.client.post(f"/api/requests/{request_id}/fund",
                                    json={"repay_amount": "180.00",
                                          "repay_date": "2027-05-01"})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self.event_types(request_id), ["created", "funded"])

    def test_a_failed_funding_leaves_no_funded_event(self):
        request_id, _ = services.save_loan_request(
            "borrower", self.TITLE, "https://example.com/p", datetime.now(), "post6")
        self.make_user("stranger", role="borrower")
        loan_id, error = services.fund_loan_request(
            request_id, "stranger", 180.0, "2027-05-01")
        self.assertIsNotNone(error)
        self.assertEqual(self.event_types(request_id), ["created"])

    def test_one_request_cannot_be_funded_twice(self):
        request_id, _ = services.save_loan_request(
            "borrower", self.TITLE, "https://example.com/p", datetime.now(), "post7")
        self.make_user("lender2", role="lender", verified_lender=True)
        first, error = services.fund_loan_request(request_id, "lender", 180.0, "2027-05-01")
        self.assertIsNone(error)
        second, error = services.fund_loan_request(request_id, "lender2", 180.0, "2027-05-01")
        self.assertIsNone(second)
        self.assertIsNotNone(error)
        self.assertEqual(self.event_types(request_id), ["created", "funded"])
        self.assertEqual(self.query("SELECT COUNT(*) FROM loans")[0][0], 1)

    # -- later lifecycle ----------------------------------------------------

    def test_status_change_records_from_and_to(self):
        request_id, _ = services.create_loan_request(borrower_username="borrower")
        services.update_request_status(request_id, "expired", actor="mod", note="stale")
        types = self.event_types(request_id)
        self.assertEqual(types, ["created", "status_changed"])
        note = self.query(
            "SELECT note FROM request_events WHERE event_type = 'status_changed'")[0][0]
        self.assertIn("open -> expired", note)
        self.assertIn("stale", note)

    def test_admin_override_is_visible_on_the_timeline(self):
        request_id, _ = services.create_loan_request(borrower_username="borrower")
        services.update_request_status(request_id, "funded", actor="mod")
        services.update_request_status(request_id, "open", actor="admin", force=True)
        notes = [row[0] for row in self.query(
            "SELECT note FROM request_events WHERE request_id = %s ORDER BY id",
            (request_id,))]
        self.assertIn("admin override", notes[-1])

    def test_linking_records_the_loan(self):
        request_id, _ = services.create_loan_request(borrower_username="borrower")
        loan_id, _ = services.create_loan(
            lender="lender", borrower="borrower", amount=Decimal("100.00"),
            currency="USD", thread_url="https://example.com/t",
            repay_amount=Decimal("110.00"), repay_date="2027-01-01")
        db_id = self.query("SELECT id FROM loans WHERE loan_id = %s", (loan_id,))[0][0]
        ok, error = services.link_request_to_loan(request_id, db_id, actor="mod")
        self.assertIsNone(error, error)
        self.assertEqual(self.event_types(request_id), ["created", "linked_to_loan"])

    def test_linking_cannot_resurrect_a_removed_request(self):
        request_id, _ = services.create_loan_request(borrower_username="borrower")
        services.update_request_status(request_id, "removed", actor="mod")
        loan_id, _ = services.create_loan(
            lender="lender", borrower="borrower", amount=Decimal("100.00"),
            currency="USD", thread_url="https://example.com/t2",
            repay_amount=Decimal("110.00"), repay_date="2027-01-01")
        db_id = self.query("SELECT id FROM loans WHERE loan_id = %s", (loan_id,))[0][0]
        ok, error = services.link_request_to_loan(request_id, db_id, actor="mod")
        self.assertFalse(ok)
        status = self.query(
            "SELECT request_status FROM loan_requests WHERE request_id = %s",
            (request_id,))[0][0]
        self.assertEqual(status, "removed")

    def test_cancelling_records_an_event(self):
        request_id, _ = services.save_loan_request(
            "borrower", self.TITLE, "https://example.com/p", datetime.now(), "post8")
        result, error = services.cancel_loan_request(
            request_id, actor="mod", actor_role="mod", note="borrower withdrew")
        self.assertIsNone(error, error)
        self.assertEqual(self.event_types(request_id), ["created", "status_changed"])

    def test_the_full_lifecycle_reads_in_order(self):
        request_id, _ = services.save_loan_request(
            "borrower", self.TITLE, "https://example.com/p", datetime.now(), "post9")
        services.fund_loan_request(request_id, "lender", 180.0, "2027-05-01")
        events, error = services.get_request_events(request_id)
        self.assertIsNone(error)
        self.assertEqual([e["event_type"] for e in events], ["created", "funded"])
