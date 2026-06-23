"""
Reddit OAuth authentication for LoanCentral dashboard.

Requires a Reddit *web app* (not script) with:
  - redirect URI matching DASHBOARD_REDIRECT_URI
  - scope: identity

Set in .env:
  DASHBOARD_CLIENT_ID=...
  DASHBOARD_CLIENT_SECRET=...
  DASHBOARD_REDIRECT_URI=http://localhost:5000/auth/callback
"""

import os
import time
from collections import defaultdict

import requests as _requests

REDDIT_CLIENT_ID     = os.getenv("DASHBOARD_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("DASHBOARD_CLIENT_SECRET", "")
REDDIT_REDIRECT_URI  = os.getenv("DASHBOARD_REDIRECT_URI", "http://localhost:5000/auth/callback")
REDDIT_USER_AGENT    = "LoanCentral Dashboard/1.0"

# ---- Rate limiting ----
# Max 5 login attempts per IP per 15 minutes.
# NOTE: this dict is shared by all login methods (OAuth, API key, OTP) so
# an attacker cannot bypass per-method limits by alternating between them.
_login_attempts: dict = defaultdict(list)
_RATE_LIMIT        = 5
_RATE_WINDOW       = 900       # seconds (15 min)
_last_gc: float    = 0.0
_GC_INTERVAL       = 600       # sweep the whole dict every 10 min


def oauth_configured() -> bool:
    """Return True if OAuth credentials are present."""
    return bool(REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET)


def get_auth_url(state: str) -> str:
    """Build the Reddit OAuth authorization URL."""
    return (
        "https://www.reddit.com/api/v1/authorize"
        f"?client_id={REDDIT_CLIENT_ID}"
        f"&response_type=code"
        f"&state={state}"
        f"&redirect_uri={REDDIT_REDIRECT_URI}"
        f"&duration=temporary"
        f"&scope=identity"
    )


def exchange_code(code: str) -> tuple:
    """
    Exchange an OAuth code for a Reddit username.
    Returns (username, None) on success, or (None, error_string) on failure.
    """
    try:
        token_resp = _requests.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDDIT_REDIRECT_URI,
            },
            headers={"User-Agent": REDDIT_USER_AGENT},
            timeout=10,
        )
    except _requests.RequestException as e:
        return None, f"Network error during token exchange: {e}"

    if not token_resp.ok:
        return None, f"Reddit rejected token exchange (HTTP {token_resp.status_code})"

    token = token_resp.json().get("access_token")
    if not token:
        return None, "No access token in Reddit response"

    try:
        me_resp = _requests.get(
            "https://oauth.reddit.com/api/v1/me",
            headers={
                "Authorization": f"bearer {token}",
                "User-Agent": REDDIT_USER_AGENT,
            },
            timeout=10,
        )
    except _requests.RequestException as e:
        return None, f"Network error fetching user info: {e}"

    if not me_resp.ok:
        return None, f"Failed to fetch Reddit user info (HTTP {me_resp.status_code})"

    username = me_resp.json().get("name", "").strip().lower()
    if not username:
        return None, "Could not determine Reddit username"

    return username, None


def check_rate_limit(ip: str) -> bool:
    """Return True if this IP is allowed to attempt login, False if blocked.

    Performs periodic full sweeps of the dict so IPs that never reach their
    limit don't accumulate forever (the per-access prune only helps active IPs).
    """
    global _last_gc
    now = time.time()
    cutoff = now - _RATE_WINDOW

    # Periodic full-dict sweep to evict cold entries.
    if now - _last_gc > _GC_INTERVAL:
        stale = [k for k, v in _login_attempts.items() if not v or max(v) < cutoff]
        for k in stale:
            del _login_attempts[k]
        _last_gc = now

    _login_attempts[ip] = [t for t in _login_attempts[ip] if t > cutoff]
    if len(_login_attempts[ip]) >= _RATE_LIMIT:
        return False
    _login_attempts[ip].append(now)
    return True
