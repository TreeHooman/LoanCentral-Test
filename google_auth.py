"""Sign in with Google (OpenID Connect, authorization-code flow with PKCE).

Only the `openid email` scopes are requested: Google's permanent account ID
(`sub`) and the address. No Google data is read beyond that, and nothing is
stored except those two values (accounts.py).

Configuration (Render environment):
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
  GOOGLE_REDIRECT_URI  optional; defaults to DASHBOARD_URL + /auth/google/callback
"""

import base64
import hashlib
import json
import os
import secrets
import time
from urllib.parse import urlencode

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")


def configured():
    return bool((os.getenv("GOOGLE_CLIENT_ID") or "").strip()
                and (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip())


def redirect_uri():
    explicit = (os.getenv("GOOGLE_REDIRECT_URI") or "").strip()
    if explicit:
        return explicit
    # Same default as the bot's links: Google needs an absolute address, and a
    # missing DASHBOARD_URL produced "/auth/google/callback", which it rejects.
    from bot_messages import DASHBOARD_URL
    base = ((os.getenv("DASHBOARD_URL") or "").strip() or DASHBOARD_URL
            or "https://loancentral.net").rstrip("/")
    return f"{base}/auth/google/callback"


def new_flow():
    """(state, code_verifier) for one sign-in attempt; keep both in the session."""
    return secrets.token_urlsafe(24), secrets.token_urlsafe(48)


def authorize_url(state, code_verifier):
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return AUTH_URL + "?" + urlencode({
        "client_id": os.getenv("GOOGLE_CLIENT_ID", "").strip(),
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": "openid email",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    })


def _claims(id_token):
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return None


def exchange_code(code, code_verifier):
    """Trade the callback's code for the Google account. Returns (account, error).

    account = {"sub": ..., "email": ...}. The ID token comes straight from
    Google's token endpoint over TLS, which OpenID Connect accepts in place of
    checking its signature (Core §3.1.3.7); issuer, audience and expiry are
    still checked.
    """
    import requests
    try:
        response = requests.post(TOKEN_URL, data={
            "code": code,
            "client_id": os.getenv("GOOGLE_CLIENT_ID", "").strip(),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
            "redirect_uri": redirect_uri(),
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        }, timeout=10)
    except Exception:
        return None, "Couldn't reach Google. Try again."
    if response.status_code != 200:
        return None, "Google didn't accept the sign-in. Try again."
    claims = _claims((response.json() or {}).get("id_token", ""))
    if not claims:
        return None, "Google's reply couldn't be read. Try again."
    if claims.get("iss") not in ISSUERS:
        return None, "Unexpected sign-in issuer."
    if claims.get("aud") != os.getenv("GOOGLE_CLIENT_ID", "").strip():
        return None, "That sign-in wasn't for LoanCentral."
    if int(claims.get("exp", 0)) < time.time():
        return None, "The sign-in expired. Try again."
    if not claims.get("sub"):
        return None, "Google didn't return an account."
    return {"sub": str(claims["sub"]), "email": claims.get("email")}, None
