"""Guards the Reddit free-tier budget: every outgoing PRAW request must pass
through reddit_limiter, and the cap must stay under Reddit's 100 QPM."""

import utils
from utils import _RedditRateLimiter, _ThrottledRequestor


class TestRateLimiter:
    def test_cap_is_under_reddit_free_tier(self):
        assert utils.reddit_limiter._limit <= 90, (
            "Limiter cap must stay safely under Reddit's 100 requests/min free tier"
        )

    def test_no_sleep_under_cap(self, monkeypatch):
        slept = []
        monkeypatch.setattr(utils.time, "sleep", lambda s: slept.append(s))
        lim = _RedditRateLimiter(calls_per_minute=3)
        for _ in range(3):
            lim.wait()
        assert slept == []

    def test_sleeps_when_cap_hit(self, monkeypatch):
        slept = []
        monkeypatch.setattr(utils.time, "sleep", lambda s: slept.append(s))
        lim = _RedditRateLimiter(calls_per_minute=2)
        for _ in range(3):
            lim.wait()
        assert len(slept) == 1
        assert 0 < slept[0] <= 60.1


class TestThrottledRequestor:
    def test_praw_client_uses_throttled_requestor(self):
        assert utils.reddit._core._requestor.__class__ is _ThrottledRequestor

    def test_wait_called_before_every_request(self, monkeypatch):
        calls = []
        monkeypatch.setattr(utils.reddit_limiter, "wait", lambda: calls.append("wait"))
        monkeypatch.setattr(
            _ThrottledRequestor.__mro__[1], "request",
            lambda self, *a, **kw: calls.append("request"),
        )
        requestor = _ThrottledRequestor.__new__(_ThrottledRequestor)
        requestor.request("GET", "https://oauth.reddit.com/x")
        assert calls == ["wait", "request"]
