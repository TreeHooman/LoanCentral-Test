"""`$loan` offers and the borrower's `$confirm` (as the original bot worked).

A `$loan` on Reddit is an offer. It only becomes a loan — on anyone's record,
in stats, in history — once the borrower confirms it with `$confirm`. Without
that step a flaired lender could put a debt on someone who never agreed to it.

Offers live in loan_offers (migration 018) until confirmed or expired.
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal

logger = logging.getLogger("LoanCentral")

#: How long a borrower has to confirm an offer.
OFFER_DAYS = 7


def _db():
    from services import _get_db
    return _get_db()


def _expire_old(cur):
    cur.execute("UPDATE loan_offers SET status = 'expired' WHERE status = 'open' AND expires_at < %s",
                (datetime.now(),))


def create_offer(lender, borrower, amount, currency, thread_url):
    """Record a `$loan` offer. Returns (offer, error).

    Repeating the same `$loan` in the same thread returns the open offer
    instead of adding another. offer = {"id", "created"}.
    """
    from services import normalize_username
    lender, borrower = normalize_username(lender), normalize_username(borrower)
    amount = Decimal(str(amount))
    currency = (currency or "").upper()
    if not lender or not borrower:
        return None, "Missing lender or borrower."
    if lender == borrower:
        return None, "You cannot lend to yourself."
    if amount <= 0:
        return None, "Loan amount must be greater than zero."
    conn = _db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()
        _expire_old(cur)
        cur.execute("""
            SELECT id FROM loan_offers
            WHERE status = 'open' AND lender = %s AND borrower = %s AND amount = %s
              AND currency = %s AND COALESCE(thread_url, '') = COALESCE(%s, '')
        """, (lender, borrower, amount, currency, thread_url))
        row = cur.fetchone()
        if row:
            conn.commit()
            return {"id": row[0], "created": False}, None
        cur.execute("""
            INSERT INTO loan_offers (lender, borrower, amount, currency, thread_url,
                                     status, created_at, expires_at)
            VALUES (%s, %s, %s, %s, %s, 'open', %s, %s)
        """, (lender, borrower, amount, currency, thread_url, datetime.now(),
              datetime.now() + timedelta(days=OFFER_DAYS)))
        cur.execute("SELECT MAX(id) FROM loan_offers WHERE lender = %s AND borrower = %s",
                    (lender, borrower))
        offer_id = cur.fetchone()[0]
        conn.commit()
        return {"id": offer_id, "created": True}, None
    except Exception as e:
        conn.rollback()
        logger.error(f"create_offer error: {e}", exc_info=True)
        return None, str(e)
    finally:
        conn.close()


def open_offers_for(borrower):
    """The borrower's open offers, newest first: list of dicts."""
    from services import normalize_username
    conn = _db()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        _expire_old(cur)
        conn.commit()
        cur.execute("""
            SELECT id, lender, amount, currency, thread_url FROM loan_offers
            WHERE status = 'open' AND borrower = %s ORDER BY id DESC
        """, (normalize_username(borrower),))
        return [{"id": r[0], "lender": r[1], "amount": Decimal(str(r[2])), "currency": r[3],
                 "thread_url": r[4]} for r in cur.fetchall()]
    finally:
        conn.close()


def pick_offer(borrower, lender=None, amount=None, currency=None, thread_url=None):
    """Choose which open offer a `$confirm` means. Returns (offer, error).

    Whatever the borrower wrote narrows the choice: a lender, an amount, a
    currency. With nothing written, the offer in this thread is used, or their
    only open offer. Anything still ambiguous is an error asking them to say
    which one.
    """
    from services import normalize_username
    offers = open_offers_for(borrower)
    if not offers:
        return None, "You have no loan offers waiting for confirmation."
    if lender:
        offers = [o for o in offers if o["lender"] == normalize_username(lender)]
    if amount is not None:
        offers = [o for o in offers if o["amount"] == Decimal(str(amount))]
    if currency:
        offers = [o for o in offers if o["currency"] == currency.upper()]
    if not offers:
        return None, "No open loan offer matches that. Check the lender and amount."
    if len(offers) > 1 and thread_url:
        here = [o for o in offers if o["thread_url"] == thread_url]
        if len(here) == 1:
            return here[0], None
    if len(offers) > 1:
        listing = ", ".join(f"u/{o['lender']} {o['amount']:.2f} {o['currency']}" for o in offers[:5])
        return None, ("You have more than one offer waiting: " + listing +
                      ". Confirm one with `$confirm u/lender amount currency`.")
    return offers[0], None


def confirm_offer(offer_id, borrower):
    """Turn an offer into a loan. Returns (loan_db_id, offer, error).

    Only the offer's borrower can confirm it. The offer is claimed with a
    single guarded UPDATE, so a double-posted `$confirm` makes one loan.
    """
    from services import create_loan, normalize_username
    borrower = normalize_username(borrower)
    conn = _db()
    if not conn:
        return None, None, "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE loan_offers SET status = 'confirming'
            WHERE id = %s AND borrower = %s AND status = 'open' AND expires_at > %s
        """, (offer_id, borrower, datetime.now()))
        if cur.rowcount != 1:
            conn.rollback()
            return None, None, "That offer is no longer open."
        cur.execute("SELECT lender, borrower, amount, currency, thread_url FROM loan_offers WHERE id = %s",
                    (offer_id,))
        lender, borrower, amount, currency, thread_url = cur.fetchone()
        conn.commit()
    finally:
        conn.close()

    offer = {"id": offer_id, "lender": lender, "borrower": borrower,
             "amount": Decimal(str(amount)), "currency": currency}
    # Loans recorded on Reddit keep just the amount: no repay amount or date.
    db_id, error = create_loan(lender, borrower, Decimal(str(amount)), currency, thread_url or "")

    conn = _db()
    try:
        cur = conn.cursor()
        if error:
            cur.execute("UPDATE loan_offers SET status = 'open' WHERE id = %s", (offer_id,))
        else:
            cur.execute("""
                UPDATE loan_offers SET status = 'confirmed', loan_db_id = %s, confirmed_at = %s
                WHERE id = %s
            """, (db_id, datetime.now(), offer_id))
        conn.commit()
    finally:
        conn.close()
    if error:
        return None, offer, error
    return db_id, offer, None
