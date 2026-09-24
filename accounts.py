"""Accounts proven through Reddit, signed in with Google.

How someone gets an account (no keys, no emailed codes):

  1. On Reddit they comment `$login`. The bot DMs *that account* a one-time
     setup link (commands/login_command.py). Only the real account can read its
     DMs, so following the link proves the Reddit name.
  2. The link opens "create your account" — it does not sign anyone in. There
     they connect a Google account, which is stored against the Reddit name.
  3. From then on they sign in with Google. If they lose that Google account,
     `$login` again lets them connect a new one (it replaces the old link).

Only Google's permanent account ID (`sub`) identifies them; the address is
kept for display, since a Gmail address can change or be reused.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta

logger = logging.getLogger("LoanCentral")

#: How long a DM'd setup link works. Long enough to find the DM, short enough
#: that an old message sitting in an inbox is useless.
SETUP_LINK_MINUTES = 30

#: Setup links per Reddit account per hour. Each one is a DM from the bot.
SETUP_LINKS_PER_HOUR = 3


def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _db():
    from services import _get_db
    return _get_db()


def create_setup_link(reddit_username):
    """Issue a one-time setup link token for a Reddit account.

    Returns (token, error). The token is shown once (in the DM); only its hash
    is stored. Refuses past SETUP_LINKS_PER_HOUR so `$login` can't be used to
    make the bot spam someone's inbox.
    """
    from services import normalize_username
    name = normalize_username(reddit_username)
    if not name:
        return None, "No Reddit username."
    conn = _db()
    if not conn:
        return None, "Database connection failed"
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM account_setup_links
            WHERE reddit_username = %s AND created_at > %s
        """, (name, datetime.now() - timedelta(hours=1)))
        if (cur.fetchone()[0] or 0) >= SETUP_LINKS_PER_HOUR:
            return None, "rate_limited"
        token = secrets.token_urlsafe(32)
        cur.execute("""
            INSERT INTO account_setup_links (reddit_username, token_hash, created_at, expires_at)
            VALUES (%s, %s, %s, %s)
        """, (name, _hash(token), datetime.now(),
              datetime.now() + timedelta(minutes=SETUP_LINK_MINUTES)))
        conn.commit()
        return token, None
    except Exception as e:
        conn.rollback()
        logger.error(f"create_setup_link error: {e}", exc_info=True)
        return None, str(e)
    finally:
        conn.close()


def peek_setup_link(token):
    """The Reddit name a still-valid setup link is for, without using it up.

    Returns (reddit_username, error). Used to show "create your account for
    u/name" before the person goes off to Google.
    """
    if not token:
        return None, "This link is not valid."
    conn = _db()
    if not conn:
        return None, "Database connection failed"
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT reddit_username, expires_at, used_at FROM account_setup_links
            WHERE token_hash = %s
        """, (_hash(token),))
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None, "This link is not valid."
    if row[2] is not None:
        return None, "This link has already been used. Comment $login again for a new one."
    expires = row[1] if isinstance(row[1], datetime) else datetime.fromisoformat(str(row[1]))
    if expires < datetime.now():
        return None, "This link has expired. Comment $login again for a new one."
    return row[0], None


def consume_setup_link(token):
    """Use up a setup link. Returns (reddit_username, error).

    A single UPDATE, so two tabs racing on the same link can't both win.
    """
    if not token:
        return None, "This link is not valid."
    conn = _db()
    if not conn:
        return None, "Database connection failed"
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE account_setup_links SET used_at = %s
            WHERE token_hash = %s AND used_at IS NULL AND expires_at > %s
        """, (datetime.now(), _hash(token), datetime.now()))
        if cur.rowcount != 1:
            conn.rollback()
            return None, "This link has expired or was already used. Comment $login again for a new one."
        cur.execute("SELECT reddit_username FROM account_setup_links WHERE token_hash = %s",
                    (_hash(token),))
        name = cur.fetchone()[0]
        conn.commit()
        return name, None
    except Exception as e:
        conn.rollback()
        logger.error(f"consume_setup_link error: {e}", exc_info=True)
        return None, str(e)
    finally:
        conn.close()


def connect_google_account(reddit_username, google_sub, google_email=None):
    """Connect a Google account to the LoanCentral account for a Reddit name.

    Called only after a setup link proved the Reddit name. Creates the account
    if this is the person's first time (role borrower, unless they already have
    one — flaired lenders are recorded by `$login` before the DM goes out).
    Replaces any Google account connected before: that is how a lost Google
    account is recovered.

    Returns (dashboard_username, error).
    """
    from services import log_audit, normalize_username, resolve_user_identity
    name = normalize_username(reddit_username)
    sub = (google_sub or "").strip()
    if not name or not sub:
        return None, "Missing account details."

    identity, err = resolve_user_identity(name)
    if err:
        return None, err
    username = (identity or {}).get("username") or name

    conn = _db()
    if not conn:
        return None, "Database connection failed"
    try:
        cur = conn.cursor()
        cur.execute("SELECT username FROM user_roles WHERE google_sub = %s AND lower(username) != %s",
                    (sub, username.lower()))
        other = cur.fetchone()
        if other:
            # Two LoanCentral accounts sharing one Google login would let one
            # person sign in as either. Refuse rather than move it silently.
            return None, (f"That Google account is already connected to u/{other[0]}. "
                          "Use a different Google account.")
        cur.execute("SELECT google_sub FROM user_roles WHERE lower(username) = %s", (username.lower(),))
        existing = cur.fetchone()
        now = datetime.now()
        if existing is None:
            cur.execute("""
                INSERT INTO user_roles (username, role, reddit_username, reddit_username_linked_at,
                                        reddit_username_linked_by, google_sub, google_email,
                                        google_linked_at, perm_version)
                VALUES (%s, 'borrower', %s, %s, 'reddit-dm', %s, %s, %s, 1)
            """, (username.lower(), name, now, sub, google_email, now))
        else:
            # perm_version bump: any session signed in with the *previous*
            # Google account is ended on its next request.
            cur.execute("""
                UPDATE user_roles
                SET google_sub = %s, google_email = %s, google_linked_at = %s,
                    reddit_username = COALESCE(reddit_username, %s),
                    perm_version = COALESCE(perm_version, 0) + 1
                WHERE lower(username) = %s
            """, (sub, google_email, now, name, username.lower()))
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"connect_google_account error: {e}", exc_info=True)
        return None, str(e)
    finally:
        conn.close()

    replaced = bool(existing and existing[0] and existing[0] != sub)
    log_audit(username, "self", "google_account_connected", "user", username,
              new_value={"reddit_username": name, "google_email": google_email,
                         "replaced_previous": replaced})
    return username, None


def find_account_by_google(google_sub):
    """(username, perm_version) for a connected Google account, or (None, None)."""
    if not google_sub:
        return None, None
    conn = _db()
    if not conn:
        return None, None
    try:
        cur = conn.cursor()
        cur.execute("SELECT username, perm_version FROM user_roles WHERE google_sub = %s",
                    (google_sub,))
        row = cur.fetchone()
        return (row[0], row[1]) if row else (None, None)
    finally:
        conn.close()
