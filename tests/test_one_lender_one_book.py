"""A lender sees every loan they made, whichever interface recorded it.

The bot records a loan under the lender's Reddit handle; the dashboard under
their dashboard username. When the two differ, the lender dashboard, stats and
profile must still show one combined book.
"""

from tests.support.dbcase import RealDBTestCase


class OneLenderOneBookTests(RealDBTestCase):
    def setUp(self):
        super().setUp()
        self.make_user("dashlender", role="lender", verified_lender=True)
        self.execute("UPDATE user_roles SET reddit_username = %s WHERE username = %s",
                     ("RedditLender", "dashlender"))
        # One loan booked by the bot (Reddit handle, as Reddit spells it) and
        # one booked on the dashboard (dashboard username).
        self.add_loan("B-1", "RedditLender", "borrower1", 100)
        self.add_loan("D-1", "dashlender", "borrower2", 250)
        self.add_loan("X-1", "someoneelse", "borrower3", 999)
        self.login("dashlender", role="lender")

    def add_loan(self, loan_id, lender, borrower, amount):
        self.execute(
            "INSERT INTO loans (loan_id, lender, borrower, amount, amount_repaid, currency, status, "
            "date_created, original_thread) "
            "VALUES (%s, %s, %s, %s, 0, 'USD', 'confirmed', CURRENT_TIMESTAMP, 'https://reddit.com/x')",
            (loan_id, lender, borrower, amount),
        )

    def test_the_lender_dashboard_lists_bot_and_dashboard_loans(self):
        response = self.client.get("/api/loans?lender=dashlender&limit=200")
        self.assertEqual(response.status_code, 200)
        ids = sorted(loan["loan_id"] for loan in response.get_json())
        self.assertEqual(ids, ["B-1", "D-1"])

    def test_lender_stats_count_both(self):
        response = self.client.get("/api/stats/lender/dashlender")
        self.assertEqual(response.status_code, 200)
        stats = response.get_json()
        self.assertEqual(stats["total_loans"], 2)
        self.assertEqual(float(stats["total_lent"]), 350.0)

    def test_the_reddit_handle_resolves_to_the_same_book(self):
        import services
        loans, error = services.get_loan_history("redditlender", role="lender")
        self.assertIsNone(error)
        self.assertEqual(sorted(l["loan_id"] for l in loans), ["B-1", "D-1"])

    def test_due_reminders_include_bot_loans(self):
        self.execute("UPDATE loans SET repay_date = CURRENT_DATE")
        response = self.client.get("/api/reminders?lender=dashlender&days=3")
        self.assertEqual(response.status_code, 200)
        ids = sorted(item["loan_id"] for item in response.get_json()["items"])
        self.assertEqual(ids, ["B-1", "D-1"])
