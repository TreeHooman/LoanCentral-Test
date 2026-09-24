"""Google rejects a relative redirect address, so it must always be absolute."""

import os
import unittest
from unittest.mock import patch

import google_auth


class RedirectUriTests(unittest.TestCase):
    def test_uses_dashboard_url(self):
        with patch.dict(os.environ, {"DASHBOARD_URL": "https://example.test/", "GOOGLE_REDIRECT_URI": ""}):
            self.assertEqual(google_auth.redirect_uri(), "https://example.test/auth/google/callback")

    def test_missing_dashboard_url_still_gives_an_absolute_address(self):
        with patch.dict(os.environ, {"DASHBOARD_URL": "", "GOOGLE_REDIRECT_URI": ""}):
            uri = google_auth.redirect_uri()
        self.assertTrue(uri.startswith("https://"), uri)
        self.assertTrue(uri.endswith("/auth/google/callback"), uri)

    def test_explicit_setting_wins(self):
        with patch.dict(os.environ, {"GOOGLE_REDIRECT_URI": "https://x.test/cb"}):
            self.assertEqual(google_auth.redirect_uri(), "https://x.test/cb")


if __name__ == "__main__":
    unittest.main()
