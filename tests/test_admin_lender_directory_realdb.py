"""Admin lender directory must list every lender, not just dashboard accounts.

Lenders from the old bot's history (e.g. mods who have never signed in) have
loans but no user_roles row, and used to be invisible to admins.
"""

import services
from tests.support.dbcase import RealDBTestCase


class AdminLenderDirectoryTests(RealDBTestCase):
    def add_loan(self, loan_id, lender, status="repaid"):
        self.execute(
            "INSERT INTO loans (loan_id, lender, borrower, amount, amount_repaid, currency, status, "
            "date_created, original_thread) "
            "VALUES (%s, %s, 'someborrower', 100, 0, 'USD', %s, CURRENT_TIMESTAMP, 'https://reddit.com/x')",
            (loan_id, lender, status),
        )

    def lenders(self, **kw):
        rows, total, error = services.list_lenders(**kw)
        self.assertIsNone(error)
        return {r["username"]: r for r in rows}, total

    def test_lender_without_account_is_listed(self):
        self.add_loan("L-1", "Logistix1")
        self.add_loan("L-2", "logistix1", "confirmed")
        rows, total = self.lenders()
        self.assertEqual(total, 1)
        self.assertEqual(rows["logistix1"]["total_loans"], 2)
        self.assertEqual(rows["logistix1"]["active_loans"], 1)

    def test_loans_under_reddit_handle_count_for_the_account(self):
        self.make_user("dashname", role="lender")
        self.execute("UPDATE user_roles SET reddit_username = 'RedditName' WHERE username = 'dashname'")
        self.add_loan("L-1", "RedditName")
        self.add_loan("L-2", "dashname")
        rows, total = self.lenders()
        # One entry for the person, not a second ghost row for the Reddit handle.
        self.assertEqual(total, 1)
        self.assertEqual(rows["dashname"]["total_loans"], 2)

    def test_filters_still_apply(self):
        self.make_user("vl", role="lender", verified_lender=True)
        self.add_loan("L-1", "oldlender")
        rows, _ = self.lenders(verified_filter="verified")
        self.assertEqual(set(rows), {"vl"})
        rows, _ = self.lenders(q="old")
        self.assertEqual(set(rows), {"oldlender"})

    def test_admin_api_lists_them(self):
        self.make_user("boss", role="admin")
        self.login("boss", role="admin")
        self.add_loan("L-1", "left-associate3911")
        res = self.client.get("/api/admin/lenders")
        self.assertEqual(res.status_code, 200)
        names = [r["username"] for r in res.get_json()["lenders"]]
        self.assertIn("left-associate3911", names)
