"""Trust tiers: the more loans completed, the higher the rank.

A loan counts once it is fully repaid (a simple count, owner decision
2026-09-24): for a lender, loans they made that were repaid; for a borrower,
loans they repaid. Counted across every name an account uses (Reddit handle and
dashboard username), like the rest of the record.

Legacy Lender is separate: a role an admin grants by hand (founders). It sits
alongside the earned tier and takes priority in flair.

Thresholds (repaid loans -> tier), highest first. Borrowers have their own
list, which starts the same; set BORROWER_TIERS to change it, e.g.
"Diamond:60,Platinum:30,Gold:15,Silver:8,Bronze:4,Iron:1".
"""

import os

LENDER_TIERS = (("Diamond", 500), ("Platinum", 200), ("Gold", 100),
                ("Silver", 50), ("Bronze", 25), ("Iron", 1))

LEGACY = "Legacy"


def _parse(spec):
    tiers = []
    for part in (spec or "").split(","):
        name, _, number = part.partition(":")
        if name.strip() and number.strip().isdigit():
            tiers.append((name.strip(), int(number)))
    return tuple(sorted(tiers, key=lambda t: t[1], reverse=True))


def thresholds(role):
    if role == "borrower":
        return _parse(os.getenv("BORROWER_TIERS")) or LENDER_TIERS
    return LENDER_TIERS


def tier_for(count, role="lender"):
    """Tier name for a number of repaid loans, or None below the first tier."""
    for name, minimum in thresholds(role):
        if count >= minimum:
            return name
    return None


def next_tier(count, role="lender"):
    """(next tier name, loans still needed), or (None, 0) at the top."""
    for name, minimum in reversed(thresholds(role)):
        if count < minimum:
            return name, minimum - count
    return None, 0


def repaid_counts(username):
    """(repaid as lender, repaid as borrower) across all the account's names."""
    from services import _alias_match, _get_db, account_aliases
    aliases = account_aliases(username)
    lender_sql, lender_params = _alias_match("lender", aliases)
    borrower_sql, borrower_params = _alias_match("borrower", aliases)
    conn = _get_db()
    if not conn:
        return 0, 0
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT
              COALESCE(SUM(CASE WHEN {lender_sql} THEN 1 ELSE 0 END), 0),
              COALESCE(SUM(CASE WHEN {borrower_sql} THEN 1 ELSE 0 END), 0)
            FROM loans WHERE status = 'repaid'
        """, (*lender_params, *borrower_params))
        row = cur.fetchone()
        return int(row[0] or 0), int(row[1] or 0)
    finally:
        conn.close()


def is_legacy(username):
    from services import _get_db, resolve_user_identity
    identity, _ = resolve_user_identity(username)
    name = (identity or {}).get("username") or (username or "").lower()
    conn = _get_db()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("SELECT legacy_lender FROM user_roles WHERE lower(username) = %s", (name,))
        row = cur.fetchone()
        return bool(row and row[0])
    except Exception:
        return False
    finally:
        conn.close()


def standing(username):
    """Everything shown about someone's rank, in one dict."""
    lent, borrowed = repaid_counts(username)
    lender_next, lender_needed = next_tier(lent, "lender")
    borrower_next, borrower_needed = next_tier(borrowed, "borrower")
    return {
        "lender_repaid": lent,
        "lender_tier": tier_for(lent, "lender"),
        "lender_next_tier": lender_next,
        "lender_loans_to_next": lender_needed,
        "borrower_repaid": borrowed,
        "borrower_tier": tier_for(borrowed, "borrower"),
        "borrower_next_tier": borrower_next,
        "borrower_loans_to_next": borrower_needed,
        "legacy": is_legacy(username),
    }


def lender_label(username, standing_=None):
    """"Legacy" or the lender tier, for bot replies and flair; None if neither."""
    s = standing_ or standing(username)
    return LEGACY if s["legacy"] else s["lender_tier"]


def flair_text(username, base="Verified Lender"):
    """The lender flair to show: "Verified Lender · Gold" / "· Legacy" / plain."""
    label = lender_label(username)
    return f"{base} · {label}" if label else base
