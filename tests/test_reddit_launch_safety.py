"""
Launch-safety guards for the live Reddit API:
  - a compliant, self-identifying User-Agent
  - refusing to start with an incomplete live configuration
  - not re-firing commands out of quoted or fenced text
  - backing off when Reddit says the request budget is nearly gone
"""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import utils
from utils import _RedditRateLimiter, reddit_config_problems, user_agent_problems


class UserAgentTests(unittest.TestCase):
    def test_placeholder_user_agent_is_rejected(self):
        problems = user_agent_problems("LoanCentralBot/1.0 by your_username", "loancentralbot")
        self.assertTrue(problems)
        self.assertIn("placeholder", problems[0])

    def test_empty_user_agent_is_rejected(self):
        self.assertTrue(user_agent_problems("", "loancentralbot"))

    def test_compliant_user_agent_passes(self):
        self.assertEqual(
            user_agent_problems("python:loancentral-bot:1.0 (by /u/LoanCentralBot)", "LoanCentralBot"),
            [],
        )

    def test_user_agent_must_identify_the_account(self):
        problems = user_agent_problems("python:loancentral-bot:1.0", "LoanCentralBot")
        self.assertTrue(any("identify the account" in p for p in problems))


class ConfigPreflightTests(unittest.TestCase):
    GOOD = {
        "REDDIT_CLIENT_ID": "abc",
        "REDDIT_CLIENT_SECRET": "def",
        "REDDIT_USERNAME": "LoanCentralBot",
        "REDDIT_PASSWORD": "hunter2",
        "SUBREDDITS": "LoanCentral",
        "REDDIT_USER_AGENT": "python:loancentral-bot:1.0 (by /u/LoanCentralBot)",
        "DASHBOARD_URL": "https://loancentral-dashboard.onrender.com",
    }

    def test_complete_config_has_no_problems(self):
        with patch.dict(os.environ, self.GOOD, clear=False):
            self.assertEqual(reddit_config_problems(), [])

    def test_missing_credentials_are_reported(self):
        env = dict(self.GOOD, REDDIT_CLIENT_ID="", REDDIT_PASSWORD="")
        with patch.dict(os.environ, env, clear=False):
            problems = reddit_config_problems()
        self.assertTrue(any("REDDIT_CLIENT_ID" in p for p in problems))
        self.assertTrue(any("REDDIT_PASSWORD" in p for p in problems))

    def test_missing_subreddit_is_reported(self):
        env = dict(self.GOOD, SUBREDDITS="", SUBREDDIT="")
        with patch.dict(os.environ, env, clear=False):
            problems = reddit_config_problems()
        self.assertTrue(any("SUBREDDITS" in p for p in problems))

    def test_missing_dashboard_url_is_reported(self):
        env = dict(self.GOOD, DASHBOARD_URL="")
        with patch.dict(os.environ, env, clear=False):
            problems = reddit_config_problems()
        self.assertTrue(any("DASHBOARD_URL" in p for p in problems))

    def test_plain_http_dashboard_url_is_reported(self):
        env = dict(self.GOOD, DASHBOARD_URL="http://loancentral-dashboard.onrender.com")
        with patch.dict(os.environ, env, clear=False):
            problems = reddit_config_problems()
        self.assertTrue(any("https://" in p for p in problems))


class ServerBudgetBackoffTests(unittest.TestCase):
    def test_low_remaining_triggers_hold(self):
        lim = _RedditRateLimiter(calls_per_minute=80)
        lim.note_response(SimpleNamespace(headers={
            "x-ratelimit-remaining": "2", "x-ratelimit-reset": "30",
        }))
        self.assertGreater(lim._hold_until, 0)
        self.assertEqual(lim.last_remaining, 2)

    def test_healthy_budget_does_not_hold(self):
        lim = _RedditRateLimiter(calls_per_minute=80)
        lim.note_response(SimpleNamespace(headers={
            "x-ratelimit-remaining": "90", "x-ratelimit-reset": "30",
        }))
        self.assertEqual(lim._hold_until, 0.0)

    def test_missing_or_junk_headers_are_ignored(self):
        lim = _RedditRateLimiter(calls_per_minute=80)
        for headers in ({}, None, {"x-ratelimit-remaining": "nope", "x-ratelimit-reset": "x"}):
            lim.note_response(SimpleNamespace(headers=headers))
        self.assertEqual(lim._hold_until, 0.0)

    def test_non_response_return_value_is_safe(self):
        _RedditRateLimiter(calls_per_minute=80).note_response(None)


class CommandableTextTests(unittest.TestCase):
    def setUp(self):
        import main
        self.strip = main.CommandManager._commandable_text

    def test_plain_command_survives(self):
        self.assertIn("$refunded 41", self.strip("$refunded 41"))

    def test_quoted_command_is_ignored(self):
        self.assertNotIn("$refunded", self.strip("> $refunded 41\n\nI did not send that."))

    def test_html_escaped_quote_is_ignored(self):
        self.assertNotIn("$refunded", self.strip("&gt; $refunded 41"))

    def test_fenced_block_is_ignored(self):
        self.assertNotIn("$paid_with_id", self.strip("see:\n```\n$paid_with_id 12 25 USD\n```\n"))

    def test_command_after_a_quote_still_runs(self):
        text = self.strip("> some quoted context\n\n$unpaid 31")
        self.assertIn("$unpaid 31", text)


if __name__ == "__main__":
    unittest.main()
