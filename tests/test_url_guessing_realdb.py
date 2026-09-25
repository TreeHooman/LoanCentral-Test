"""URL guessing: typing addresses you shouldn't have must not work.

Walks every route in the app as a signed-out visitor, a borrower, a lender and
a mod, filling each <param> with something that belongs to *someone else*
(another borrower's loan, another lender's request, the admin's name...).

- Signed out: only the public pages answer with content.
- Borrower / lender: nothing under the mod or admin areas answers, and no
  other person's loan or request can be read or changed.
- Mod: nothing under the admin-only areas answers.

A new route is covered automatically. If it fails here, add the right gate to
the route; don't add it to the allow-lists below unless it really is public.
"""

import re
from decimal import Decimal

import services
from tests.support.dbcase import RealDBTestCase

#: Pages anyone may open without signing in.
PUBLIC = {
    "/", "/login", "/login/borrower", "/terms", "/privacy", "/ping", "/health",
    "/api/announcements", "/auth/dev-login",
}
#: Sign-in plumbing: reachable signed out by design (they only redirect or
#: validate a token / key and never return account data without one).
AUTH_FLOW = (
    "/auth/", "/account/setup/", "/view/", "/api/auth/borrower/",
)

MOD_AREAS = ("/api/admin/", "/dashboard/admin", "/admin", "/api/mod/", "/mod/",
             "/dashboard/mod", "/api/reddit-actions", "/api/activity",
             "/api/verification", "/api/integrations/", "/api/requests",
             "/api/loan-requests")


def _admin_only_rules():
    """(method, rule) pairs whose route is gated to admins only, read from the
    decorators in api/app.py so a new admin route is covered automatically."""
    import pathlib
    lines = (pathlib.Path(__file__).resolve().parents[1] / "api" / "app.py").read_text(
        encoding="utf-8").splitlines()
    found = set()
    for i, line in enumerate(lines):
        m = re.match(r'@app\.route\("([^"]+)"(.*)\)', line)
        if not m:
            continue
        methods = re.findall(r'"(GET|POST|PUT|PATCH|DELETE)"', m.group(2)) or ["GET"]
        j, decorators = i + 1, []
        while not lines[j].startswith("def "):
            decorators.append(lines[j].strip())
            j += 1
        if any(d in ('@role_required("admin")', "@require_admin_api", "@admin_required")
               for d in decorators):
            found.update((meth, m.group(1)) for meth in methods)
    return found


#: Mod-area paths a borrower/lender legitimately uses for their *own* data.
OWN_DATA_OK = {
    "/api/loan-requests/mine", "/api/verification/apply",
    "/api/loan-requests",          # POST: create your own request (checked in the route)
}
#: Verified lenders may open a request to fund it (the Reddit post is public).
LENDER_OK = {"/api/requests/<request_id>"}


def _ok(code):
    return 200 <= code < 300


class UrlGuessingTests(RealDBTestCase):
    def setUp(self):
        super().setUp()
        for name, role, verified in (
            ("boss", "admin", False), ("moddy", "mod", False),
            ("lendera", "lender", True), ("lenderb", "lender", True),
            ("boba", "borrower", False), ("bobb", "borrower", False),
        ):
            self.make_user(name, role=role, verified_lender=verified)
        self.loan_b, error = services.create_loan(
            lender="lenderb", borrower="bobb", amount=Decimal("100"), currency="USD",
            thread_url="https://example.com/b", repay_amount=Decimal("120"),
            repay_date="2027-01-01")
        self.assertIsNone(error)
        self.execute(
            "INSERT INTO loan_requests (request_id, borrower_username, reddit_post_id) "
            "VALUES ('REQ-BOBB', 'bobb', 'abc123')")

    def _url(self, rule):
        values = {
            "loan_id": self.loan_b, "username": "bobb", "lender": "lenderb",
            "request_id": "REQ-BOBB", "token": "not-a-real-token",
        }
        def fill(m):
            conv, name = m.group(1), m.group(2)
            if conv and conv.startswith("int"):
                return "1"
            return values.get(name, "x")
        return re.sub(r"<(?:(\w+(?:\([^)]*\))?):)?(\w+)>", fill, rule)

    def _routes(self):
        for rule in self.web.app.url_map.iter_rules():
            if rule.endpoint == "static" or rule.rule.startswith(("/auth/logout", "/auth/dev-login")):
                continue   # these would sign the test user out (or in as someone else)
            for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
                yield method, rule.rule, self._url(rule.rule)

    def _call(self, method, url):
        self.web._api_rate_hits.clear()   # the sweep is a burst; don't test the rate limiter here
        kwargs = {"headers": {"Origin": "http://localhost"}}
        if method != "GET":
            kwargs["json"] = {"borrower": "bobb", "lender": "lenderb", "amount": 1,
                              "legacy": True, "role": "admin"}
        return self.client.open(url, method=method, **kwargs).status_code

    def _sweep(self):
        hits = []
        for method, rule, url in self._routes():
            code = self._call(method, url)
            if _ok(code):
                hits.append((method, rule, code))
        return hits

    def test_signed_out_sees_only_public_pages(self):
        self.logout()
        leaks = [(m, r) for m, r, _ in self._sweep()
                 if r not in PUBLIC and not r.startswith(AUTH_FLOW)]
        self.assertEqual(leaks, [])

    def _assert_no_mod_areas(self, who, role):
        self.login(who, role=role)
        allowed = OWN_DATA_OK | (LENDER_OK if role == "lender" else set())
        leaks = [(m, r) for m, r, _ in self._sweep()
                 if r.startswith(MOD_AREAS) and r not in allowed]
        self.assertEqual(leaks, [], f"{role} reached mod/admin routes")

    def test_borrower_cannot_reach_mod_or_admin_areas(self):
        self._assert_no_mod_areas("boba", "borrower")

    def test_lender_cannot_reach_mod_or_admin_areas(self):
        self._assert_no_mod_areas("lendera", "lender")

    def test_mod_cannot_reach_admin_only_areas(self):
        self.login("moddy", role="mod")
        admin_only = _admin_only_rules()
        self.assertGreater(len(admin_only), 10)
        leaks = [(m, r) for m, r, _ in self._sweep() if (m, r) in admin_only]
        self.assertEqual(leaks, [])

    def test_nobody_else_can_read_or_change_someone_elses_loan(self):
        for who, role in (("boba", "borrower"), ("lendera", "lender")):
            self.login(who, role=role)
            allowed = LENDER_OK if role == "lender" else set()
            leaks = [(m, r) for m, r, _ in self._sweep()
                     if ("<loan_id>" in r or "<request_id>" in r) and r not in allowed]
            self.assertEqual(leaks, [], f"{who} reached another person's loan/request")
        status = self.query("SELECT status FROM loans WHERE loan_id = %s", (self.loan_b,))[0][0]
        self.assertEqual(status, "confirmed")

    def test_lender_cannot_act_on_a_role_they_do_not_have(self):
        """Changing a role or a key through a guessed URL must fail."""
        self.login("lendera", role="lender")
        self.client.post("/api/admin/roles/lendera", json={"role": "admin"},
                         headers={"Origin": "http://localhost"})
        role = self.query("SELECT role FROM user_roles WHERE username = 'lendera'")[0][0]
        self.assertEqual(role, "lender")


class StoredLinkTests(RealDBTestCase):
    """A loan's thread link is shown as a clickable link, so only web links
    are ever stored (a javascript: link would run code for whoever clicks)."""

    def test_only_web_links_are_kept(self):
        self.assertEqual(services.web_url_or_blank("https://reddit.com/r/x"), "https://reddit.com/r/x")
        for bad in ("javascript:alert(1)", " JaVa\tScript:x", "data:text/html,x", "vbscript:x"):
            self.assertEqual(services.web_url_or_blank(bad), "", bad)
        self.assertEqual(services.web_url_or_blank("dashboard"), "dashboard")

    def test_create_loan_drops_a_script_link(self):
        self.make_user("lendera", role="lender", verified_lender=True)
        loan_id, error = services.create_loan(
            lender="lendera", borrower="boba", amount=Decimal("10"), currency="USD",
            thread_url="javascript:alert(1)")
        self.assertIsNone(error)
        stored = self.query("SELECT original_thread FROM loans WHERE loan_id = %s", (loan_id,))[0][0]
        self.assertEqual(stored or "", "")
