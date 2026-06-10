"""
LoanCentral Service Layer
-------------------------
All core business logic lives here.
Bot commands call these functions.
Future API/dashboard will call the same functions.
"""

import time
import logging
import json
import os
from datetime import datetime, timedelta
from decimal import Decimal

logger = logging.getLogger("LoanCentral")


def _get_db():
    """Lazy import so tests can patch utils."""
    from utils import get_db_connection
    return get_db_connection()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_loan_id():
    """Generate a unique loan ID based on current timestamp."""
    return str(int(time.time()))


def _looks_like_missing_column(error):
    msg = str(error).lower()
    return "does not exist" in msg and "column" in msg


def log_event(event_type: str, actor: str = None, actor_role: str = None,
              target_user: str = None, loan_id: str = None, request_id: str = None,
              source: str = "system", details: dict = None):
    """
    Best-effort immutable audit/activity log.
    This never blocks the bot/dashboard action if the audit table is missing.
    """
    conn = _get_db()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        if getattr(conn, "is_sqlite", False):
            details_value = json.dumps(details or {})
        else:
            try:
                from psycopg2.extras import Json
                details_value = Json(details or {})
            except Exception:
                details_value = json.dumps(details or {})
        cur.execute("""
            INSERT INTO audit_events
            (event_type, actor, actor_role, target_user, loan_id, request_id, source, details, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            event_type,
            actor.lower() if isinstance(actor, str) else actor,
            actor_role,
            target_user.lower() if isinstance(target_user, str) else target_user,
            str(loan_id) if loan_id is not None else None,
            request_id,
            source,
            details_value,
            datetime.now(),
        ))
        conn.commit()
        return True
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.debug(f"audit log skipped for {event_type}: {e}")
        return False
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


def get_recent_activity(limit: int = 50):
    """Return recent audit events for mod/dashboard activity feeds."""
    limit = max(1, min(int(limit or 50), 200))
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, event_type, actor, actor_role, target_user, loan_id,
                   request_id, source, details, created_at
            FROM audit_events
            ORDER BY created_at DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        events = []
        for r in rows:
            details = r[8] or {}
            if isinstance(details, str):
                try:
                    details = json.loads(details)
                except json.JSONDecodeError:
                    details = {"raw": details}
            events.append({
                "id": r[0],
                "event_type": r[1],
                "actor": r[2],
                "actor_role": r[3],
                "target_user": r[4],
                "loan_id": r[5],
                "request_id": r[6],
                "source": r[7],
                "details": details,
                "created_at": r[9].isoformat() if r[9] else None,
            })
        return events, None
    except Exception as e:
        logger.error(f"get_recent_activity error: {e}", exc_info=True)
        return None, "Database error fetching activity."
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Reddit Action Queue
# ---------------------------------------------------------------------------

def enqueue_reddit_action(action_type: str, target_user: str = None, loan_id: str = None,
                          request_id: str = None, subreddit: str = None, payload: dict = None,
                          reason: str = None, created_by: str = None):
    """
    Stage an outbound Reddit action for review/execution.
    This function never calls Reddit.
    """
    allowed = {"reminder_comment", "lender_dm", "ban_user", "flair_sync", "funded_comment", "repaid_comment"}
    action_type = (action_type or "").strip().lower()
    if action_type not in allowed:
        return None, f"Unsupported reddit action type: {action_type}."
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()
        if getattr(conn, "is_sqlite", False):
            payload_value = json.dumps(payload or {})
        else:
            try:
                from psycopg2.extras import Json
                payload_value = Json(payload or {})
            except Exception:
                payload_value = json.dumps(payload or {})
        cur.execute("""
            SELECT id, status FROM reddit_actions
            WHERE action_type = %s
              AND status = 'queued'
              AND COALESCE(target_user, '') = COALESCE(%s, '')
              AND COALESCE(loan_id, '') = COALESCE(%s, '')
              AND COALESCE(request_id, '') = COALESCE(%s, '')
            ORDER BY created_at DESC
            LIMIT 1
        """, (
            action_type,
            target_user.lower() if isinstance(target_user, str) else target_user,
            str(loan_id) if loan_id is not None else None,
            request_id,
        ))
        existing = cur.fetchone()
        if existing:
            return {
                "ok": True,
                "id": existing[0],
                "action_type": action_type,
                "status": existing[1],
                "deduped": True,
            }, None
        cur.execute("""
            INSERT INTO reddit_actions
            (action_type, status, target_user, loan_id, request_id, subreddit,
             payload, reason, created_by, created_at, updated_at)
            VALUES (%s, 'queued', %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            RETURNING id
        """, (
            action_type,
            target_user.lower() if isinstance(target_user, str) else target_user,
            str(loan_id) if loan_id is not None else None,
            request_id,
            subreddit,
            payload_value,
            reason,
            created_by.lower() if isinstance(created_by, str) else created_by,
        ))
        action_id = cur.fetchone()[0]
        conn.commit()
        log_event(
            "reddit_action_queued",
            actor=created_by,
            actor_role=None,
            target_user=target_user,
            loan_id=loan_id,
            request_id=request_id,
            source="reddit_queue",
            details={"action_type": action_type, "action_id": action_id, "reason": reason},
        )
        return {"ok": True, "id": action_id, "action_type": action_type, "status": "queued"}, None
    except Exception as e:
        conn.rollback()
        logger.error(f"enqueue_reddit_action error: {e}", exc_info=True)
        return None, "Database error queueing Reddit action."
    finally:
        cur.close()
        conn.close()


def list_reddit_actions(status: str = None, action_type: str = None, limit: int = 100):
    """List queued/history Reddit actions for mod review."""
    limit = max(1, min(int(limit or 100), 500))
    conditions, params = [], []
    if status:
        conditions.append("status = %s")
        params.append(status)
    if action_type:
        conditions.append("action_type = %s")
        params.append(action_type)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT id, action_type, status, target_user, loan_id, request_id,
                   subreddit, payload, reason, created_by, created_at, updated_at
            FROM reddit_actions
            {where}
            ORDER BY created_at DESC
            LIMIT %s
        """, tuple(params))
        rows = cur.fetchall()
        actions = []
        for r in rows:
            payload = r[7] or {}
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    payload = {"raw": payload}
            actions.append({
                "id": r[0],
                "action_type": r[1],
                "status": r[2],
                "target_user": r[3],
                "loan_id": r[4],
                "request_id": r[5],
                "subreddit": r[6],
                "payload": payload,
                "reason": r[8],
                "created_by": r[9],
                "created_at": r[10].isoformat() if r[10] else None,
                "updated_at": r[11].isoformat() if r[11] else None,
            })
        return actions, None
    except Exception as e:
        logger.error(f"list_reddit_actions error: {e}", exc_info=True)
        return None, "Database error fetching Reddit action queue."
    finally:
        cur.close()
        conn.close()


def update_reddit_action_status(action_id: int, status: str, actor: str = None, reason: str = None):
    """Update a queued Reddit action status. Does not call Reddit."""
    status = (status or "").strip().lower()
    if status not in ("queued", "sent", "skipped", "failed", "cancelled"):
        return None, "Invalid Reddit action status."
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE reddit_actions
            SET status = %s,
                reason = COALESCE(NULLIF(%s, ''), reason),
                updated_at = NOW()
            WHERE id = %s
            RETURNING id, action_type, target_user, loan_id, request_id
        """, (status, reason or "", action_id))
        row = cur.fetchone()
        if not row:
            return None, "Reddit action not found."
        conn.commit()
        log_event(
            "reddit_action_status_changed",
            actor=actor,
            target_user=row[2],
            loan_id=row[3],
            request_id=row[4],
            source="reddit_queue",
            details={"action_id": row[0], "action_type": row[1], "status": status, "reason": reason},
        )
        return {"ok": True, "id": row[0], "status": status}, None
    except Exception as e:
        conn.rollback()
        logger.error(f"update_reddit_action_status error: {e}", exc_info=True)
        return None, "Database error updating Reddit action."
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Loan Services
# ---------------------------------------------------------------------------

def create_loan(lender: str, borrower: str, amount: Decimal, currency: str, thread_url: str,
                repay_amount: Decimal = None, repay_date: str = None, payment_method: str = None,
                interest_amount: Decimal = None, interest_rate: Decimal = None):
    """
    Confirm and save a new loan to the database.
    Returns (loan_db_id, error_message).
    On success: (int, None)
    On failure: (None, str)
    """
    if amount <= 0:
        return None, "Loan amount must be greater than zero."

    if lender == borrower:
        return None, "Lender and borrower cannot be the same person."

    conn = _get_db()
    if not conn:
        return None, "Database connection failed."

    try:
        cur = conn.cursor()

        # Block exact duplicate confirmations (same lender, borrower, amount, currency, thread)
        cur.execute('''
            SELECT id FROM loans
            WHERE lender = %s AND borrower = %s AND amount = %s
              AND currency = %s AND original_thread = %s AND status = 'confirmed'
            ORDER BY date_created DESC LIMIT 1
        ''', (lender, borrower, amount, currency, thread_url))
        if cur.fetchone():
            return None, f"You have already confirmed this loan with u/{lender}."

        loan_id = _generate_loan_id()

        # Derive interest from repay_amount if not explicitly provided
        if repay_amount and repay_amount > amount:
            if interest_amount is None:
                interest_amount = repay_amount - amount
            if interest_rate is None and amount > 0:
                interest_rate = ((repay_amount - amount) / amount * 100).quantize(Decimal("0.01"))

        inserted_public_id = True
        try:
            cur.execute('''
                INSERT INTO loans
                (loan_id, lender, borrower, amount, currency, date_created, original_thread,
                 status, repay_amount, repay_date, payment_method, interest_amount, interest_rate)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            ''', (
                loan_id, lender, borrower, amount, currency, datetime.now(), thread_url,
                'confirmed', repay_amount, repay_date or None, payment_method or None,
                interest_amount, interest_rate
            ))
        except Exception as e:
            if not _looks_like_missing_column(e):
                raise
            conn.rollback()
            cur = conn.cursor()
            inserted_public_id = False
            cur.execute('''
                INSERT INTO loans
                (lender, borrower, amount, currency, date_created, original_thread, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            ''', (lender, borrower, amount, currency, datetime.now(), thread_url, 'confirmed'))

        db_id = cur.fetchone()[0]
        if not inserted_public_id:
            loan_id = str(db_id)

        # Update lender stats
        cur.execute('''
            INSERT INTO users (username, loans_as_lender, amount_lent, last_updated)
            VALUES (%s, 1, %s, %s)
            ON CONFLICT (username) DO UPDATE SET
                loans_as_lender = users.loans_as_lender + 1,
                amount_lent = users.amount_lent + %s,
                last_updated = %s
        ''', (lender, amount, datetime.now(), amount, datetime.now()))

        # Update borrower stats
        cur.execute('''
            INSERT INTO users (username, loans_as_borrower, amount_borrowed, last_updated)
            VALUES (%s, 1, %s, %s)
            ON CONFLICT (username) DO UPDATE SET
                loans_as_borrower = users.loans_as_borrower + 1,
                amount_borrowed = users.amount_borrowed + %s,
                last_updated = %s
        ''', (borrower, amount, datetime.now(), amount, datetime.now()))

        conn.commit()
        logger.info(f"Loan created: {lender} -> {borrower} {amount} {currency} (id={db_id}, loan_id={loan_id})")
        log_event("loan_created", actor=lender, actor_role="lender", target_user=borrower,
                  loan_id=loan_id, source="service",
                  details={"amount": str(amount), "currency": currency, "thread_url": thread_url})
        log_audit(lender, "lender", "loan_created", "loan", loan_id,
                  new_value={"lender": lender, "borrower": borrower,
                             "amount": str(amount), "currency": currency})
        add_loan_event(loan_id, "loan_created", lender,
                       f"Loan of {amount} {currency} confirmed for u/{borrower}")
        # Notify both parties
        create_notification(
            borrower, "loan_confirmed",
            "New loan confirmed",
            f"u/{lender} has recorded a loan of {amount} {currency} for you (ID: {loan_id}). "
            "Log in to view the details.")
        create_notification(
            lender, "loan_confirmed",
            "Loan recorded",
            f"Loan {loan_id} for u/{borrower} ({amount} {currency}) has been recorded.")
        return loan_id, None

    except Exception as e:
        conn.rollback()
        logger.error(f"create_loan error: {e}", exc_info=True)
        return None, "Database error while creating loan."
    finally:
        cur.close()
        conn.close()


def mark_repaid(loan_id: str, amount_paid: Decimal, currency: str, actor: str, actor_role: str = "lender", payment_timing: str = None):
    """
    Record a repayment on a loan.
    actor_role: "lender" (paid_with_id) or "borrower" (repaid command)
    Returns (updated_loan_dict, error_message)
    """
    if amount_paid <= 0:
        return None, "Payment amount must be greater than zero."

    conn = _get_db()
    if not conn:
        return None, "Database connection failed."

    try:
        cur = conn.cursor()

        schema_mode = "dashboard"
        try:
            cur.execute('''
                SELECT id, loan_id, lender, borrower, amount, amount_repaid, currency, status,
                       COALESCE(repay_amount, amount)
                FROM loans
                WHERE id::text = %s OR loan_id = %s
                ORDER BY id DESC LIMIT 1
            ''', (loan_id, loan_id))
        except Exception as e:
            if not _looks_like_missing_column(e):
                raise
            conn.rollback()
            schema_mode = "base"
            cur = conn.cursor()
            cur.execute('''
                SELECT id, lender, borrower, amount, amount_repaid, currency, status
                FROM loans
                WHERE id::text = %s
                ORDER BY id DESC LIMIT 1
            ''', (loan_id,))

        result = cur.fetchone()
        if not result:
            logger.warning(f"No loan found for ID {loan_id} by {actor}")
            return None, f"Could not find a loan with ID {loan_id}. Please check the loan ID from the confirmation message."

        if schema_mode == "base":
            db_id, public_id = result[0], str(result[0])
            lender, borrower, principal_amount, already_repaid, loan_currency, status = result[1:7]
            repay_total = principal_amount
        else:
            db_id, public_id, lender, borrower, principal_amount, already_repaid, loan_currency, status, repay_total = result

        # Role check (case-insensitive — stored names may differ in case from session username)
        if actor_role == "lender" and actor.lower() != lender.lower():
            logger.warning(f"Payment auth mismatch for loan {loan_id}: actor={actor}, lender={lender}")
            return None, f"Loan ID {loan_id} exists, but it is recorded under lender u/{lender}. Only that lender can use $paid_with_id for this loan."
        if actor_role == "borrower" and actor.lower() != borrower.lower():
            logger.warning(f"Repaid auth mismatch for loan {loan_id}: actor={actor}, borrower={borrower}")
            return None, f"No loan {loan_id} found where you are the borrower."

        # Status checks
        if status == "repaid":
            return None, "This loan has already been fully repaid."
        if status == "refunded":
            return None, "This loan has been refunded and cannot be marked repaid."

        # Currency check
        if loan_currency != currency:
            return None, f"Currency mismatch. Loan is in {loan_currency}, you specified {currency}."

        loan_amount = Decimal(repay_total)
        already_repaid = Decimal(already_repaid)
        remaining = loan_amount - already_repaid

        # Allow up to 50% over the original repay_amount (total cap, not per payment).
        # Any excess over the remaining balance is silently treated as full settlement.
        max_allowed = loan_amount * Decimal("1.5") - already_repaid
        if amount_paid > max_allowed:
            return None, f"Payment amount {amount_paid:.2f} {currency} exceeds the maximum allowed for this loan."
        if amount_paid > remaining:
            amount_paid = remaining  # treat overpayment as exact settlement

        # Normalise timing value
        _timing = payment_timing if payment_timing in ("early", "late", "on_time") else None

        new_repaid = already_repaid + amount_paid
        new_status = "repaid" if new_repaid >= loan_amount else "partially_repaid"

        cur.execute('''
            UPDATE loans SET amount_repaid = %s, status = %s, last_updated = %s, payment_timing = %s WHERE id = %s
        ''', (new_repaid, new_status, datetime.now(), _timing, db_id))

        cur.execute('''
            UPDATE users SET amount_repaid = amount_repaid + %s, last_updated = %s WHERE username = %s
        ''', (amount_paid, datetime.now(), borrower))

        if status == "unpaid":
            if new_status == "repaid":
                cur.execute('''
                    UPDATE users SET
                        unpaid_loans = GREATEST(unpaid_loans - 1, 0),
                        unpaid_amount = GREATEST(unpaid_amount - %s, 0),
                        last_updated = %s
                    WHERE username = %s
                ''', (amount_paid, datetime.now(), borrower))
            else:
                cur.execute('''
                    UPDATE users SET
                        unpaid_amount = GREATEST(unpaid_amount - %s, 0),
                        last_updated = %s
                    WHERE username = %s
                ''', (amount_paid, datetime.now(), borrower))

        conn.commit()
        logger.info(f"Repayment recorded: {borrower} paid {amount_paid} {currency} to {lender} (loan {db_id})")
        _lid = public_id or str(db_id)
        timing_label = {"early": " (early)", "late": " (late)", "on_time": ""}.get(_timing or "", "")
        log_event("payment_recorded", actor=actor, actor_role=actor_role, target_user=borrower,
                  loan_id=_lid, source="service",
                  details={"amount_paid": str(amount_paid), "currency": currency,
                           "new_status": new_status, "payment_timing": _timing,
                           "remaining": str(max(loan_amount - new_repaid, Decimal("0.00")))})
        log_audit(actor, actor_role, "loan_repaid" if new_status == "repaid" else "payment_recorded",
                  "loan", _lid, new_value={"amount_paid": str(amount_paid),
                                           "new_status": new_status, "currency": currency,
                                           "payment_timing": _timing})
        add_loan_event(_lid, "loan_repaid" if new_status == "repaid" else "payment_partial",
                       actor, f"{amount_paid} {currency} received{timing_label} — status: {new_status}")
        # Notify lender of payment
        payment_msg = (
            f"u/{borrower} has fully repaid loan {_lid} ({amount_paid} {loan_currency})."
            if new_status == "repaid" else
            f"u/{borrower} recorded a payment of {amount_paid} {loan_currency} on loan {_lid}. "
            f"Status: {new_status}."
        )
        create_notification(lender, "payment_received", "Payment received", payment_msg)

        return {
            "db_id": db_id,
            "lender": lender,
            "borrower": borrower,
            "loan_amount": Decimal(principal_amount),
            "repay_amount": loan_amount,
            "new_repaid": new_repaid,
            "remaining": max(loan_amount - new_repaid, Decimal("0.00")),
            "currency": loan_currency,
            "new_status": new_status,
        }, None

    except Exception as e:
        conn.rollback()
        logger.error(f"mark_repaid error: {e}", exc_info=True)
        return None, "Database error while recording payment."
    finally:
        cur.close()
        conn.close()


def mark_unpaid(loan_id: str, lender: str):
    """
    Mark a loan as unpaid. Lender only — borrower is looked up from the loan record.
    Returns (loan_dict, error_message)
    """
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."

    try:
        cur = conn.cursor()

        schema_mode = "dashboard"
        try:
            cur.execute('''
                SELECT id, amount, currency, amount_repaid, original_thread, status, borrower,
                       COALESCE(repay_amount, amount)
                FROM loans
                WHERE (id::text = %s OR loan_id = %s) AND lower(lender) = lower(%s)
                ORDER BY id DESC LIMIT 1
            ''', (loan_id, loan_id, lender))
        except Exception as e:
            if not _looks_like_missing_column(e):
                raise
            conn.rollback()
            schema_mode = "base"
            cur = conn.cursor()
            cur.execute('''
                SELECT id, amount, currency, amount_repaid, original_thread, status, borrower
                FROM loans
                WHERE id::text = %s AND lower(lender) = lower(%s)
                ORDER BY id DESC LIMIT 1
            ''', (loan_id, lender))

        result = cur.fetchone()
        if not result:
            logger.warning(f"No matching loan found for unpaid: ID {loan_id} by {lender}")
            return None, f"Could not find a loan with ID {loan_id} where you are the lender."

        if schema_mode == "base":
            db_id, loan_amount, loan_currency, amount_repaid, thread_url, status, borrower = result
            repay_total = loan_amount
        else:
            db_id, loan_amount, loan_currency, amount_repaid, thread_url, status, borrower, repay_total = result

        if status == "unpaid":
            return None, "This loan is already marked unpaid."
        if status == "repaid":
            return None, "This loan has already been fully repaid."
        if status == "refunded":
            return None, "This loan has been refunded."

        cur.execute('''
            UPDATE loans SET status = 'unpaid', last_updated = %s WHERE id = %s
        ''', (datetime.now(), db_id))

        remaining_unpaid = Decimal(repay_total) - Decimal(amount_repaid)
        cur.execute('''
            UPDATE users SET
                unpaid_loans = unpaid_loans + 1,
                unpaid_amount = unpaid_amount + %s,
                last_updated = %s
            WHERE username = %s
        ''', (remaining_unpaid, datetime.now(), borrower))

        conn.commit()
        logger.info(f"Loan {db_id} marked unpaid by {lender}")
        log_event("loan_marked_unpaid", actor=lender, actor_role="lender", target_user=borrower,
                  loan_id=loan_id, source="service",
                  details={"remaining_unpaid": str(remaining_unpaid), "currency": loan_currency})
        log_audit(lender, "lender", "loan_unpaid", "loan", loan_id,
                  new_value={"borrower": borrower, "remaining_unpaid": str(remaining_unpaid),
                             "currency": loan_currency})
        add_loan_event(loan_id, "loan_unpaid", lender,
                       f"Marked unpaid — {remaining_unpaid} {loan_currency} outstanding")
        # Notify borrower
        create_notification(
            borrower, "loan_unpaid",
            "Loan marked unpaid",
            f"u/{lender} has marked loan {loan_id} ({loan_amount} {loan_currency}) as unpaid. "
            "Contact your lender or a moderator if this is incorrect.")

        return {
            "db_id": db_id,
            "lender": lender,
            "borrower": borrower,
            "loan_amount": Decimal(loan_amount),
            "repay_amount": Decimal(repay_total),
            "amount_repaid": Decimal(amount_repaid),
            "currency": loan_currency,
            "thread_url": thread_url,
        }, None

    except Exception as e:
        conn.rollback()
        logger.error(f"mark_unpaid error: {e}", exc_info=True)
        return None, "Database error while marking loan unpaid."
    finally:
        cur.close()
        conn.close()


def mark_refunded(lender: str, borrower: str, amount: Decimal, currency: str):
    """
    Mark a loan as refunded and reverse stats.
    Returns (loan_dict, error_message)
    """
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."

    try:
        cur = conn.cursor()

        cur.execute('''
            SELECT id, status FROM loans
            WHERE lender = %s AND borrower = %s AND amount = %s AND currency = %s
            ORDER BY date_created DESC LIMIT 1
        ''', (lender, borrower, amount, currency))

        result = cur.fetchone()
        if not result:
            return None, f"No matching loan found from u/{lender} to u/{borrower} for {amount} {currency}."

        db_id, status = result

        if status == "refunded":
            return None, "This loan has already been marked as refunded."
        if status == "repaid":
            return None, "This loan has already been fully repaid and cannot be marked refunded."

        cur.execute('''
            UPDATE loans SET status = 'refunded', last_updated = %s WHERE id = %s
        ''', (datetime.now(), db_id))

        cur.execute('''
            UPDATE users SET
                loans_as_lender = GREATEST(loans_as_lender - 1, 0),
                amount_lent = GREATEST(amount_lent - %s, 0),
                last_updated = %s
            WHERE username = %s
        ''', (amount, datetime.now(), lender))

        cur.execute('''
            UPDATE users SET
                loans_as_borrower = GREATEST(loans_as_borrower - 1, 0),
                amount_borrowed = GREATEST(amount_borrowed - %s, 0),
                last_updated = %s
            WHERE username = %s
        ''', (amount, datetime.now(), borrower))

        conn.commit()
        logger.info(f"Loan {db_id} refunded: {lender} -> {borrower} {amount} {currency}")
        log_event(
            "loan_refunded",
            actor=lender,
            actor_role="lender",
            target_user=borrower,
            loan_id=db_id,
            source="service",
            details={"amount": str(amount), "currency": currency},
        )

        return {"db_id": db_id, "lender": lender, "borrower": borrower, "amount": amount, "currency": currency}, None

    except Exception as e:
        conn.rollback()
        logger.error(f"mark_refunded error: {e}", exc_info=True)
        return None, "Database error while marking loan refunded."
    finally:
        cur.close()
        conn.close()


def mark_refunded_by_id(loan_id: str, lender: str):
    """
    Mark a loan as refunded by loan ID. Lender only.
    Returns (loan_dict, error_message)
    """
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."

    try:
        cur = conn.cursor()

        try:
            cur.execute('''
                SELECT id, borrower, amount, currency, status
                FROM loans
                WHERE (id::text = %s OR loan_id = %s) AND lower(lender) = lower(%s)
                ORDER BY id DESC LIMIT 1
            ''', (loan_id, loan_id, lender))
        except Exception as e:
            if not _looks_like_missing_column(e):
                raise
            conn.rollback()
            cur = conn.cursor()
            cur.execute('''
                SELECT id, borrower, amount, currency, status
                FROM loans
                WHERE id::text = %s AND lower(lender) = lower(%s)
                ORDER BY id DESC LIMIT 1
            ''', (loan_id, lender))

        result = cur.fetchone()
        if not result:
            return None, f"Could not find a loan with ID {loan_id} where you are the lender."

        db_id, borrower, amount, currency, status = result
        amount = Decimal(amount)

        if status == "refunded":
            return None, "This loan has already been marked as refunded."
        if status == "repaid":
            return None, "This loan has already been fully repaid and cannot be marked refunded."

        cur.execute('''
            UPDATE loans SET status = 'refunded', last_updated = %s WHERE id = %s
        ''', (datetime.now(), db_id))

        cur.execute('''
            UPDATE users SET
                loans_as_lender = GREATEST(loans_as_lender - 1, 0),
                amount_lent = GREATEST(amount_lent - %s, 0),
                last_updated = %s
            WHERE username = %s
        ''', (amount, datetime.now(), lender))

        cur.execute('''
            UPDATE users SET
                loans_as_borrower = GREATEST(loans_as_borrower - 1, 0),
                amount_borrowed = GREATEST(amount_borrowed - %s, 0),
                last_updated = %s
            WHERE username = %s
        ''', (amount, datetime.now(), borrower))

        conn.commit()
        logger.info(f"Loan {db_id} refunded by ID: {lender} -> {borrower} {amount} {currency}")
        log_event("loan_refunded", actor=lender, actor_role="lender", target_user=borrower,
                  loan_id=loan_id, source="service",
                  details={"amount": str(amount), "currency": currency})
        log_audit(lender, "lender", "loan_refunded", "loan", loan_id,
                  new_value={"borrower": borrower, "amount": str(amount), "currency": currency})
        add_loan_event(loan_id, "loan_refunded", lender,
                       f"Loan refunded — {amount} {currency}")

        return {"db_id": db_id, "lender": lender, "borrower": borrower, "amount": amount, "currency": currency}, None

    except Exception as e:
        conn.rollback()
        logger.error(f"mark_refunded_by_id error: {e}", exc_info=True)
        return None, "Database error while marking loan refunded."
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# User Services
# ---------------------------------------------------------------------------

def _key_hash(plaintext: str) -> str:
    import hashlib
    return hashlib.sha256(plaintext.encode()).hexdigest()


def create_lender_key(username: str, created_by: str, label: str = ""):
    """Generate a new lender key. Returns (plaintext_key, error). Plaintext shown once — only hash stored."""
    import secrets as _secrets
    plaintext = "LC-" + _secrets.token_hex(24)
    hashed = _key_hash(plaintext)
    conn = _get_db()
    if not conn:
        return None, "Database connection failed"
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO lender_keys (username, key_hash, label, created_by)
            VALUES (%s, %s, %s, %s) RETURNING id
        """, (username.lower(), hashed, label or None, created_by.lower()))
        conn.commit()
        cur.close()
        return plaintext, None
    except Exception as e:
        conn.rollback()
        logger.error(f"create_lender_key error: {e}")
        return None, str(e)
    finally:
        conn.close()


def validate_lender_key(plaintext: str):
    """Validate a key. Returns (username, error) — username is None if invalid."""
    hashed = _key_hash(plaintext)
    conn = _get_db()
    if not conn:
        return None, "Database connection failed"
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT username FROM lender_keys
            WHERE key_hash = %s AND active = TRUE
        """, (hashed,))
        row = cur.fetchone()
        if not row:
            return None, "Invalid or revoked key"
        username = row[0]
        cur.execute("UPDATE lender_keys SET last_used = NOW() WHERE key_hash = %s", (hashed,))
        conn.commit()
        cur.close()
        return username, None
    except Exception as e:
        logger.error(f"validate_lender_key error: {e}")
        return None, str(e)
    finally:
        conn.close()


def list_lender_keys(username: str = None):
    """List all keys (optionally filtered by username). Returns (rows, error)."""
    conn = _get_db()
    if not conn:
        return [], "Database connection failed"
    try:
        cur = conn.cursor()
        if username:
            cur.execute("""
                SELECT id, username, label, active, created_by, created_at, last_used, revoked_at
                FROM lender_keys WHERE username = %s ORDER BY created_at DESC
            """, (username.lower(),))
        else:
            cur.execute("""
                SELECT id, username, label, active, created_by, created_at, last_used, revoked_at
                FROM lender_keys ORDER BY created_at DESC
            """)
        rows = cur.fetchall()
        cur.close()
        return [
            {
                "id": r[0], "username": r[1], "label": r[2] or "",
                "active": r[3], "created_by": r[4],
                "created_at": r[5].isoformat() if r[5] else None,
                "last_used": r[6].isoformat() if r[6] else None,
                "revoked_at": r[7].isoformat() if r[7] else None,
            }
            for r in rows
        ], None
    except Exception as e:
        logger.error(f"list_lender_keys error: {e}")
        return [], str(e)
    finally:
        conn.close()


def revoke_lender_key(key_id: int):
    """Revoke a key by its DB id. Returns (ok, error)."""
    conn = _get_db()
    if not conn:
        return False, "Database connection failed"
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE lender_keys SET active = FALSE, revoked_at = NOW()
            WHERE id = %s
        """, (key_id,))
        conn.commit()
        cur.close()
        return True, None
    except Exception as e:
        conn.rollback()
        logger.error(f"revoke_lender_key error: {e}")
        return False, str(e)
    finally:
        conn.close()


def get_user_profile(username: str):
    """
    Get loan stats for a user.
    Returns (profile_dict, error_message)
    """
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."

    try:
        cur = conn.cursor()

        cur.execute('''
            SELECT
                COALESCE(loans_as_borrower, 0),
                COALESCE(loans_as_lender, 0),
                COALESCE(amount_borrowed, 0),
                COALESCE(amount_lent, 0),
                COALESCE(amount_repaid, 0),
                COALESCE(unpaid_loans, 0),
                COALESCE(unpaid_amount, 0)
            FROM users WHERE username = %s
        ''', (username.lower(),))

        row = cur.fetchone()

        try:
            cur.execute('''
                SELECT COUNT(*), COALESCE(SUM(COALESCE(repay_amount, amount) - amount_repaid), 0)
                FROM loans WHERE borrower = %s AND status = 'confirmed'
            ''', (username.lower(),))
        except Exception as e:
            if not _looks_like_missing_column(e):
                raise
            conn.rollback()
            cur.execute('''
                SELECT COUNT(*), COALESCE(SUM(amount - amount_repaid), 0)
                FROM loans WHERE borrower = %s AND status = 'confirmed'
            ''', (username.lower(),))

        active = cur.fetchone()

        # Fetch verified_lender status from user_roles (done before early-return
        # so users who exist in user_roles but not in users still get VL data).
        try:
            cur.execute(
                """SELECT verified_lender, reddit_username,
                          verified_lender_at, verified_lender_by
                   FROM user_roles WHERE lower(username)=lower(%s)""",
                (username,))
            role_row = cur.fetchone()
        except Exception:
            role_row = None

        if not row:
            return {
                "username": username,
                "loans_as_borrower": 0,
                "loans_as_lender": 0,
                "amount_borrowed": Decimal("0"),
                "amount_lent": Decimal("0"),
                "amount_repaid": Decimal("0"),
                "unpaid_loans": 0,
                "unpaid_amount": Decimal("0"),
                "active_loans": 0,
                "active_amount": Decimal("0"),
                "verified_lender": bool(role_row[0]) if role_row else False,
                "reddit_username": role_row[1] if role_row else None,
                "verified_lender_at": role_row[2].isoformat() if role_row and role_row[2] else None,
                "verified_lender_by": role_row[3] if role_row else None,
            }, None

        return {
            "username": username,
            "loans_as_borrower": row[0],
            "loans_as_lender": row[1],
            "amount_borrowed": Decimal(row[2]),
            "amount_lent": Decimal(row[3]),
            "amount_repaid": Decimal(row[4]),
            "unpaid_loans": row[5],
            "unpaid_amount": Decimal(row[6]),
            "active_loans": active[0] if active else 0,
            "active_amount": Decimal(active[1]) if active else Decimal("0"),
            "verified_lender": bool(role_row[0]) if role_row else False,
            "reddit_username": role_row[1] if role_row else None,
            "verified_lender_at": role_row[2].isoformat() if role_row and role_row[2] else None,
            "verified_lender_by": role_row[3] if role_row else None,
        }, None

    except Exception as e:
        logger.error(f"get_user_profile error: {e}", exc_info=True)
        return None, "Database error fetching user profile."
    finally:
        cur.close()
        conn.close()


def get_loan_history(username: str, role: str = "both", limit: int = 50):
    """
    Fetch recent loans for a user.
    role: "borrower", "lender", or "both"
    Returns (list_of_loan_dicts, error_message)
    """
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."

    try:
        cur = conn.cursor()
        username = username.lower()

        if role == "borrower":
            where = "WHERE lower(borrower) = lower(%s)"
            params = (username, limit)
        elif role == "lender":
            where = "WHERE lower(lender) = lower(%s)"
            params = (username, limit)
        else:  # both
            where = "WHERE lower(borrower) = lower(%s) OR lower(lender) = lower(%s)"
            params = (username, username, limit)

        schema_mode = "dashboard"
        try:
            cur.execute(f'''
                SELECT id, loan_id, lender, borrower, amount, amount_repaid,
                       currency, status, date_created, original_thread, repay_date, notes, repay_amount,
                       payment_method, borrower_acknowledged_at, borrower_acknowledged_note,
                       interest_amount, interest_rate, payment_timing
                FROM loans {where}
                ORDER BY date_created DESC
                LIMIT %s
            ''', params)
        except Exception as e:
            if not _looks_like_missing_column(e):
                raise
            conn.rollback()
            schema_mode = "loan_id"
            try:
                cur.execute(f'''
                    SELECT id, loan_id, lender, borrower, amount, amount_repaid,
                           currency, status, date_created, original_thread
                    FROM loans {where}
                    ORDER BY date_created DESC
                    LIMIT %s
                ''', params)
            except Exception as inner:
                if not _looks_like_missing_column(inner):
                    raise
                conn.rollback()
                schema_mode = "base"
                cur.execute(f'''
                    SELECT id, lender, borrower, amount, amount_repaid,
                           currency, status, date_created, original_thread
                    FROM loans {where}
                    ORDER BY date_created DESC
                    LIMIT %s
                ''', params)

        rows = cur.fetchall()
        loans = []
        for r in rows:
            if schema_mode == "base":
                db_id, public_id = r[0], str(r[0])
                lender, borrower, amount, amount_repaid = r[1], r[2], r[3], r[4]
                currency, status, date_created, original_thread = r[5], r[6], r[7], r[8]
                repay_date, notes, raw_repay_amount, payment_method = None, None, None, None
                ack_at, ack_note = None, None
                interest_amount, interest_rate, payment_timing = None, None, None
            else:
                db_id, public_id = r[0], r[1] or str(r[0])
                lender, borrower, amount, amount_repaid = r[2], r[3], r[4], r[5]
                currency, status, date_created, original_thread = r[6], r[7], r[8], r[9]
                repay_date = r[10] if schema_mode == "dashboard" else None
                notes = r[11] if schema_mode == "dashboard" else None
                raw_repay_amount = r[12] if schema_mode == "dashboard" else None
                payment_method = r[13] if schema_mode == "dashboard" else None
                ack_at = r[14] if schema_mode == "dashboard" else None
                ack_note = r[15] if schema_mode == "dashboard" else None
                interest_amount = r[16] if schema_mode == "dashboard" else None
                interest_rate = r[17] if schema_mode == "dashboard" else None
                payment_timing = r[18] if schema_mode == "dashboard" else None
            repay_amount = Decimal(raw_repay_amount) if raw_repay_amount is not None else Decimal(amount)
            loans.append({
                "db_id": db_id,
                "loan_id": public_id,
                "lender": lender,
                "borrower": borrower,
                "amount": Decimal(amount),
                "amount_repaid": Decimal(amount_repaid),
                "currency": currency,
                "status": status,
                "date_created": date_created,
                "original_thread": original_thread,
                "repay_date": repay_date.isoformat() if repay_date else None,
                "notes": notes,
                "payment_method": payment_method,
                "borrower_acknowledged_at": ack_at.isoformat() if ack_at else None,
                "borrower_acknowledged_note": ack_note,
                "repay_amount": repay_amount,
                "remaining": repay_amount - Decimal(amount_repaid),
                "interest_amount": Decimal(interest_amount) if interest_amount is not None else None,
                "interest_rate": Decimal(interest_rate) if interest_rate is not None else None,
                "payment_timing": payment_timing,
                "schema_outdated": schema_mode != "dashboard",
            })
        return loans, None

    except Exception as e:
        logger.error(f"get_loan_history error: {e}", exc_info=True)
        return None, "Database error fetching loan history."
    finally:
        cur.close()
        conn.close()


def get_active_loans(username: str):
    """
    Fetch all outstanding (confirmed or partially_repaid) loans for a borrower.
    Returns (list_of_loan_dicts, error_message)
    """
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."

    try:
        cur = conn.cursor()
        schema_mode = "loan_id"
        try:
            cur.execute('''
                SELECT id, loan_id, lender, borrower, amount, amount_repaid,
                       currency, status, date_created, original_thread
                FROM loans
                WHERE borrower = %s AND status IN ('confirmed', 'partially_repaid')
                ORDER BY date_created ASC
            ''', (username.lower(),))
        except Exception as e:
            if not _looks_like_missing_column(e):
                raise
            conn.rollback()
            schema_mode = "base"
            cur = conn.cursor()
            cur.execute('''
                SELECT id, lender, borrower, amount, amount_repaid,
                       currency, status, date_created, original_thread
                FROM loans
                WHERE borrower = %s AND status IN ('confirmed', 'partially_repaid')
                ORDER BY date_created ASC
            ''', (username.lower(),))

        rows = cur.fetchall()
        loans = []
        for r in rows:
            if schema_mode == "base":
                db_id, public_id = r[0], str(r[0])
                lender, borrower, amount, amount_repaid = r[1], r[2], r[3], r[4]
                currency, status, date_created, original_thread = r[5], r[6], r[7], r[8]
            else:
                db_id, public_id = r[0], r[1] or str(r[0])
                lender, borrower, amount, amount_repaid = r[2], r[3], r[4], r[5]
                currency, status, date_created, original_thread = r[6], r[7], r[8], r[9]
            loans.append({
                "db_id": db_id,
                "loan_id": public_id,
                "lender": lender,
                "borrower": borrower,
                "amount": Decimal(amount),
                "amount_repaid": Decimal(amount_repaid),
                "remaining": Decimal(amount) - Decimal(amount_repaid),
                "currency": currency,
                "status": status,
                "date_created": date_created,
                "original_thread": original_thread,
            })
        return loans, None

    except Exception as e:
        logger.error(f"get_active_loans error: {e}", exc_info=True)
        return None, "Database error fetching active loans."
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Loan Request Services
# ---------------------------------------------------------------------------

import re as _re

def _parse_req_title(title: str) -> dict:
    """
    Extract loan fields from a [REQ] post title.
    Handles formats like:
      [REQ] ($150) - (#Willingboro, NJ, USA) (repay date 06/19)
      [REQ] ($150) (Vieques) (PR) (USA) (Repay $210) (06/12)
      [REQ] ($200) (#Waterloo, Ontario, Canada) (Repay on 06/22) (PayPal)
    Returns dict with keys: amount, currency, repay_amount, repay_date, payment_method
    """
    result = {"amount": None, "currency": "USD", "repay_amount": None, "repay_date": None, "payment_method": None}

    # Amount: ($150) or ($1,500)
    m = _re.search(r'\(\$([0-9,]+(?:\.[0-9]{1,2})?)\)', title)
    if m:
        result["amount"] = float(m.group(1).replace(",", ""))

    # Repay amount: (Repay $210) or (Repay $210.50)
    m = _re.search(r'\brepay\b[^)]*\$([0-9,]+(?:\.[0-9]{1,2})?)', title, _re.IGNORECASE)
    if m:
        result["repay_amount"] = float(m.group(1).replace(",", ""))

    # Repay date: (06/19) or (06/12) — MM/DD, assume current or next year
    m = _re.search(r'\b(0?[1-9]|1[0-2])/(0?[1-9]|[12][0-9]|3[01])\b', title)
    if m:
        from datetime import date
        month, day = int(m.group(1)), int(m.group(2))
        today = date.today()
        try:
            candidate = date(today.year, month, day)
            if candidate < today:
                candidate = date(today.year + 1, month, day)
            result["repay_date"] = candidate.isoformat()
        except ValueError:
            pass

    # Payment method: (PayPal), (Venmo), (CashApp), (Zelle), (crypto)
    m = _re.search(r'\b(paypal|venmo|cashapp|cash\s*app|zelle|crypto|bitcoin|btc|e-transfer|interac)\b', title, _re.IGNORECASE)
    if m:
        result["payment_method"] = m.group(1).title()

    return result


def _next_request_id() -> str:
    """Generate next REQ-XXXX id."""
    conn = _get_db()
    if not conn:
        return f"REQ-{int(time.time()) % 10000:04d}"
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM loan_requests")
        n = cur.fetchone()[0]
        return f"REQ-{n + 1:04d}"
    except Exception:
        return f"REQ-{int(time.time()) % 10000:04d}"
    finally:
        cur.close()
        conn.close()


def save_loan_request(borrower: str, title: str, thread_link: str, post_date, reddit_post_id: str = None):
    """
    Called by bot when it sees a [REQ] post that passes checks.
    Parses the title and saves to loan_requests table.
    Returns (request_id, error)
    """
    parsed = _parse_req_title(title)
    if not parsed["amount"]:
        return None, "Could not parse loan amount from title."

    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()

        # Dedup by reddit_post_id
        if reddit_post_id:
            cur.execute("SELECT request_id FROM loan_requests WHERE reddit_post_id = %s", (reddit_post_id,))
            row = cur.fetchone()
            if row:
                return row[0], None

        request_id = _next_request_id()
        expires_at = None
        try:
            days = int(os.getenv("REQUEST_EXPIRE_DAYS", "7"))
            if days > 0:
                expires_at = datetime.now() + timedelta(days=days)
        except ValueError:
            expires_at = datetime.now() + timedelta(days=7)
        cur.execute('''
            INSERT INTO loan_requests
            (request_id, borrower, amount, currency, repay_amount, repay_date,
             payment_method, expires_at, post_date, thread_link, reddit_post_id, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'open')
        ''', (
            request_id, borrower.lower(),
            parsed["amount"], parsed["currency"],
            parsed["repay_amount"], parsed["repay_date"],
            parsed["payment_method"], expires_at, post_date,
            thread_link, reddit_post_id
        ))
        conn.commit()
        logger.info(f"Loan request saved: {request_id} from u/{borrower} ({parsed['amount']} {parsed['currency']})")
        log_event(
            "request_created",
            actor=borrower,
            actor_role="borrower",
            target_user=borrower,
            request_id=request_id,
            source="bot",
            details={
                "amount": str(parsed["amount"]),
                "currency": parsed["currency"],
                "thread_link": thread_link,
                "expires_at": expires_at.isoformat() if expires_at else None,
            },
        )
        return request_id, None
    except Exception as e:
        conn.rollback()
        logger.error(f"save_loan_request error: {e}", exc_info=True)
        return None, "Database error saving loan request."
    finally:
        cur.close()
        conn.close()


def get_loan_request(request_id: str):
    """
    Fetch a loan request by REQ-XXXX id.
    Returns (request_dict, error)
    """
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute('''
            SELECT request_id, borrower, amount, currency, repay_amount,
                   repay_date, payment_method, post_date, thread_link, status,
                   funded_by, funded_date, lender_note, expires_at
            FROM loan_requests WHERE request_id = %s
        ''', (request_id.upper(),))
        row = cur.fetchone()
        if not row:
            return None, f"Request {request_id} not found."
        return {
            "request_id":     row[0],
            "borrower":       row[1],
            "amount":         row[2],
            "currency":       row[3],
            "repay_amount":   row[4],
            "repay_date":     row[5].isoformat() if row[5] else None,
            "payment_method": row[6],
            "post_date":      row[7].isoformat() if row[7] else None,
            "thread_link":    row[8],
            "status":         row[9],
            "funded_by":      row[10],
            "funded_date":    row[11].isoformat() if row[11] else None,
            "lender_note":    row[12],
            "expires_at":     row[13].isoformat() if row[13] else None,
        }, None
    except Exception as e:
        logger.error(f"get_loan_request error: {e}", exc_info=True)
        return None, "Database error fetching request."
    finally:
        cur.close()
        conn.close()


def fund_loan_request(request_id: str, lender: str, repay_amount: float, repay_date: str):
    """
    Lender confirms a loan request from the dashboard.
    Creates a live loan and marks the request as funded.
    Returns (loan_id, error)
    """
    req, err = get_loan_request(request_id)
    if err:
        return None, err
    if req["status"] != "open":
        return None, f"Request {request_id} is already {req['status']}."
    if not repay_amount or repay_amount <= 0:
        return None, "Repay amount is required."
    if not repay_date:
        return None, "Repay date is required."

    from decimal import Decimal
    loan_id, err = create_loan(
        lender=lender,
        borrower=req["borrower"],
        amount=Decimal(str(req["amount"])),
        currency=req["currency"],
        thread_url=req["thread_link"] or "",
        repay_amount=Decimal(str(repay_amount)),
        repay_date=repay_date,
        payment_method=req.get("payment_method"),
    )
    if err:
        return None, err

    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute('''
            UPDATE loan_requests
            SET status = 'funded', funded_by = %s, funded_date = %s, loan_id = %s
            WHERE request_id = %s
        ''', (lender.lower(), datetime.now(), loan_id, request_id.upper()))
        conn.commit()
        log_event(
            "request_funded",
            actor=lender,
            actor_role="lender",
            target_user=req["borrower"],
            loan_id=loan_id,
            request_id=request_id.upper(),
            source="dashboard",
            details={"repay_amount": str(repay_amount), "repay_date": repay_date, "payment_method": req.get("payment_method")},
        )
        return loan_id, None
    except Exception as e:
        conn.rollback()
        logger.error(f"fund_loan_request error: {e}", exc_info=True)
        return None, "Database error funding request."
    finally:
        cur.close()
        conn.close()


def cancel_loan_request(request_id: str, actor: str, actor_role: str = "lender", note: str = None):
    """
    Mark an open loan request as cancelled from a specific REQ-ID workflow.
    This is not a browsable marketplace action; it only records a decision on a known request.
    """
    req, err = get_loan_request(request_id)
    if err:
        return None, err
    if req["status"] != "open":
        return None, f"Request {request_id} is already {req['status']}."

    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute('''
            UPDATE loan_requests
            SET status = 'cancelled',
                lender_note = COALESCE(NULLIF(%s, ''), lender_note)
            WHERE request_id = %s AND status = 'open'
        ''', (note or "", request_id.upper()))
        if cur.rowcount == 0:
            conn.rollback()
            return None, "Request was not open."
        conn.commit()
        log_event(
            "request_cancelled",
            actor=actor,
            actor_role=actor_role,
            target_user=req["borrower"],
            request_id=request_id.upper(),
            source="dashboard",
            details={"note_length": len(note or "")},
        )
        return {"ok": True, "request_id": request_id.upper(), "status": "cancelled"}, None
    except Exception as e:
        conn.rollback()
        logger.error(f"cancel_loan_request error: {e}", exc_info=True)
        return None, "Database error cancelling request."
    finally:
        cur.close()
        conn.close()


def get_open_requests(limit: int = 100):
    """Fetch all open loan requests for dashboard display."""
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute('''
            SELECT request_id, borrower, amount, currency, repay_amount,
                   repay_date, payment_method, post_date, thread_link, status,
                   lender_note, expires_at
            FROM loan_requests
            WHERE status = 'open'
            ORDER BY post_date DESC LIMIT %s
        ''', (limit,))
        rows = cur.fetchall()
        return [
            {
                "request_id":     r[0], "borrower":       r[1],
                "amount":         r[2], "currency":        r[3],
                "repay_amount":   r[4], "repay_date":      r[5].isoformat() if r[5] else None,
                "payment_method": r[6], "post_date":       r[7].isoformat() if r[7] else None,
                "thread_link":    r[8], "status":          r[9],
                "lender_note":    r[10], "expires_at":      r[11].isoformat() if r[11] else None,
            }
            for r in rows
        ], None
    except Exception as e:
        logger.error(f"get_open_requests error: {e}", exc_info=True)
        return None, "Database error."
    finally:
        cur.close()
        conn.close()


def find_duplicate_open_requests(borrower: str, exclude_reddit_post_id: str = None, exclude_request_id: str = None):
    """
    Return open requests for the same borrower so the bot/mods can warn.
    This is not lender-facing matching; it is duplicate/stale-record protection.
    """
    conn = _get_db()
    if not conn:
        return [], "Database connection failed."
    try:
        cur = conn.cursor()
        params = [borrower.lower()]
        extra = ""
        if exclude_reddit_post_id:
            extra = "AND (reddit_post_id IS NULL OR reddit_post_id <> %s)"
            params.append(exclude_reddit_post_id)
        if exclude_request_id:
            extra += " AND request_id <> %s"
            params.append(exclude_request_id.upper())
        cur.execute(f'''
            SELECT request_id, amount, currency, post_date, thread_link
            FROM loan_requests
            WHERE borrower = %s AND status = 'open' {extra}
            ORDER BY post_date DESC
            LIMIT 5
        ''', tuple(params))
        rows = cur.fetchall()
        return [
            {
                "request_id": r[0],
                "amount": r[1],
                "currency": r[2],
                "post_date": r[3].isoformat() if r[3] else None,
                "thread_link": r[4],
            }
            for r in rows
        ], None
    except Exception as e:
        logger.error(f"find_duplicate_open_requests error: {e}", exc_info=True)
        return [], "Database error checking duplicate requests."
    finally:
        cur.close()
        conn.close()


def expire_old_requests(days: int = None):
    """Mark open requests expired after configured/requested days."""
    if days is None:
        try:
            days = int(os.getenv("REQUEST_EXPIRE_DAYS", "7"))
        except ValueError:
            days = 7
    cutoff = datetime.now() - timedelta(days=max(1, days))
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute('''
            UPDATE loan_requests
            SET status = 'expired'
            WHERE status = 'open'
              AND (
                (expires_at IS NOT NULL AND expires_at < NOW())
                OR (expires_at IS NULL AND post_date < %s)
              )
            RETURNING request_id, borrower
        ''', (cutoff,))
        rows = cur.fetchall()
        conn.commit()
        for request_id, borrower in rows:
            log_event(
                "request_expired",
                actor=None,
                target_user=borrower,
                request_id=request_id,
                source="system",
                details={"days": days},
            )
        return len(rows), None
    except Exception as e:
        conn.rollback()
        logger.error(f"expire_old_requests error: {e}", exc_info=True)
        return None, "Database error expiring requests."
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Role / Auth Services
# ---------------------------------------------------------------------------

def get_user_role(username: str):
    """
    Get dashboard role for a user.
    Returns ('borrower'|'lender'|'mod'|'admin', error_message).
    Defaults to 'borrower' if user not in user_roles table.
    """
    conn = _get_db()
    if not conn:
        return "borrower", "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute("SELECT role FROM user_roles WHERE username = %s", (username.lower(),))
        row = cur.fetchone()
        return (row[0] if row else "borrower"), None
    except Exception as e:
        logger.error(f"get_user_role error: {e}", exc_info=True)
        return "borrower", str(e)
    finally:
        cur.close()
        conn.close()


def set_user_role(username: str, role: str, actor: str = None, actor_role: str = None):
    """
    Set or update a user's dashboard role.
    role must be 'admin', 'mod', 'lender', or 'borrower'.
    Returns (True, None) on success or (None, error_message).
    """
    if role not in ("admin", "mod", "lender", "borrower"):
        return None, "Role must be 'admin', 'mod', 'lender', or 'borrower'."
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()
        # Fetch old role for audit
        cur.execute("SELECT role FROM user_roles WHERE lower(username)=lower(%s)", (username,))
        old_row = cur.fetchone()
        old_role = old_row[0] if old_row else None
        cur.execute("""
            INSERT INTO user_roles (username, role, perm_version)
            VALUES (%s, %s, 1)
            ON CONFLICT (username) DO UPDATE
              SET role = %s,
                  perm_version = COALESCE(user_roles.perm_version, 0) + 1
        """, (username.lower(), role, role))
        conn.commit()
        logger.info(f"Role set: {username} -> {role}")
        log_event("role_changed", actor=actor, actor_role=actor_role, target_user=username,
                  source="service", details={"role": role})
        log_audit(actor or "system", actor_role or "system", "role_granted", "user", username,
                  old_value={"role": old_role}, new_value={"role": role})
        return True, None
    except Exception as e:
        conn.rollback()
        logger.error(f"set_user_role error: {e}", exc_info=True)
        return None, str(e)
    finally:
        cur.close()
        conn.close()


def update_last_login(username: str):
    """Upsert user_roles on login — creates borrower record if first time."""
    conn = _get_db()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO user_roles (username, role, last_login)
            VALUES (%s, 'borrower', NOW())
            ON CONFLICT (username) DO UPDATE SET last_login = NOW()
        """, (username.lower(),))
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"update_last_login error: {e}", exc_info=True)
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Verification Services
# ---------------------------------------------------------------------------

def submit_verification_application(username: str, requested_role: str = "lender",
                                    public_note: str = "", private_note: str = ""):
    """Create or refresh a pending verification application."""
    username = (username or "").strip().lower()
    requested_role = (requested_role or "lender").strip().lower()
    if not username:
        return None, "username is required."
    if requested_role not in ("lender",):
        return None, "Only lender verification is supported right now."

    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id FROM verification_applications
            WHERE username = %s AND requested_role = %s AND status = 'pending'
            ORDER BY submitted_at DESC LIMIT 1
        """, (username, requested_role))
        existing = cur.fetchone()
        if existing:
            cur.execute("""
                UPDATE verification_applications
                SET public_note = %s, private_note = %s, submitted_at = NOW()
                WHERE id = %s
                RETURNING id
            """, (public_note, private_note, existing[0]))
        else:
            cur.execute("""
                INSERT INTO verification_applications
                (username, requested_role, public_note, private_note, status)
                VALUES (%s, %s, %s, %s, 'pending')
                RETURNING id
            """, (username, requested_role, public_note, private_note))
        app_id = cur.fetchone()[0]
        conn.commit()
        log_event(
            "verification_submitted",
            actor=username,
            actor_role="borrower",
            target_user=username,
            source="dashboard",
            details={"requested_role": requested_role},
        )
        return {"ok": True, "id": app_id, "status": "pending"}, None
    except Exception as e:
        conn.rollback()
        logger.error(f"submit_verification_application error: {e}", exc_info=True)
        return None, "Database error submitting verification application."
    finally:
        cur.close()
        conn.close()


def list_verification_applications(status: str = None, limit: int = 100):
    """List verification applications for mod review."""
    limit = max(1, min(int(limit or 100), 500))
    conditions, params = [], []
    if status:
        conditions.append("status = %s")
        params.append(status)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT va.id, va.username, va.requested_role, va.status,
                   va.public_note, va.private_note,
                   va.reviewer, va.review_note, va.submitted_at, va.reviewed_at,
                   ur.reddit_username, ur.verified_lender
            FROM verification_applications va
            LEFT JOIN user_roles ur ON lower(ur.username) = lower(va.username)
            {where}
            ORDER BY
              CASE WHEN va.status = 'pending' THEN 0 WHEN va.status = 'approved' THEN 1 ELSE 2 END,
              va.submitted_at DESC
            LIMIT %s
        """, tuple(params))
        rows = cur.fetchall()
        return [{
            "id": r[0],
            "username": r[1],
            "requested_role": r[2],
            "status": r[3],
            "public_note": r[4],
            "private_note": r[5],
            "reviewer": r[6],
            "review_note": r[7],
            "submitted_at": r[8].isoformat() if r[8] else None,
            "reviewed_at": r[9].isoformat() if r[9] else None,
            "reddit_username": r[10],
            "already_verified": bool(r[11]),
        } for r in rows], None
    except Exception as e:
        logger.error(f"list_verification_applications error: {e}", exc_info=True)
        return None, "Database error fetching verification applications."
    finally:
        cur.close()
        conn.close()


def decide_verification_application(application_id: int, decision: str, reviewer: str,
                                    review_note: str = ""):
    """
    Process a verification application decision.
    decision: 'approved' | 'denied' | 'more_info'
    - approved: grants lender role, marks verified_lender, queues flair sync
    - denied: closes application, no role change
    - more_info: re-opens to pending with mod note, notifies applicant
    """
    decision = (decision or "").strip().lower()
    reviewer = (reviewer or "").strip().lower()
    if decision not in ("approved", "denied", "more_info"):
        return None, "Decision must be approved, denied, or more_info."
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, username, requested_role, status
            FROM verification_applications
            WHERE id = %s
        """, (application_id,))
        row = cur.fetchone()
        if not row:
            return None, "Verification application not found."
        app_id, username, requested_role, old_status = row

        # more_info can be requested on any non-approved/denied application
        # approved/denied can only be applied to pending or more_info status
        if decision in ("approved", "denied") and old_status not in ("pending", "more_info"):
            return None, f"Application is already {old_status}."

        # Decide what new_status to store
        new_status = "pending" if decision == "more_info" else decision

        cur.execute("""
            UPDATE verification_applications
            SET status = %s, reviewer = %s, review_note = %s, reviewed_at = NOW()
            WHERE id = %s
        """, (new_status, reviewer, review_note, app_id))
        conn.commit()

        if decision == "approved" and requested_role == "lender":
            role_ok, role_error = set_user_role(username, "lender")
            if role_error:
                return None, role_error
            # Also mark verified_lender on user_roles
            set_verified_lender(username, True, reviewer,
                                review_note or "Approved via verification application")
            enqueue_reddit_action(
                "flair_sync",
                target_user=username,
                subreddit=os.getenv("PRIMARY_SUBREDDIT") or (os.getenv("SUBREDDITS", "").split(",")[0].strip() or None),
                payload={"flair_text": "Verified Lender", "requested_role": requested_role},
                reason="Verification approved; Reddit flair sync pending test/live integration.",
                created_by=reviewer,
            )

        # Audit log
        action_map = {
            "approved": "verification_approved",
            "denied":   "verification_denied",
            "more_info": "verification_more_info_requested",
        }
        log_audit(reviewer, "mod", action_map[decision],
                  "user", username,
                  new_value={"decision": decision, "requested_role": requested_role,
                             "review_note": review_note})

        log_event(
            "verification_decided",
            actor=reviewer,
            actor_role="mod",
            target_user=username,
            source="dashboard",
            details={"decision": decision, "requested_role": requested_role},
        )

        # Notify applicant
        if decision == "approved":
            create_notification(
                username, "verification_approved",
                "Lender Verification Approved",
                "Your lender verification application has been approved. "
                "You now have access to lender features on the dashboard.")
        elif decision == "denied":
            msg = "Your lender verification application was not approved."
            if review_note:
                msg += f" Moderator note: {review_note}"
            create_notification(username, "verification_denied",
                                "Lender Verification Not Approved", msg)
        elif decision == "more_info":
            msg = "A moderator has reviewed your verification application and needs additional information."
            if review_note:
                msg += f" Note: {review_note}"
            create_notification(username, "verification_more_info",
                                "Verification: Additional Information Requested", msg)

        return {"ok": True, "id": app_id, "username": username, "status": new_status,
                "decision": decision}, None
    except Exception as e:
        conn.rollback()
        logger.error(f"decide_verification_application error: {e}", exc_info=True)
        return None, "Database error deciding verification application."
    finally:
        cur.close()
        conn.close()


def dispute_loan(loan_id: str, borrower: str):
    """
    Borrower flags a loan as disputed — puts it in mod review queue.
    Returns (loan_dict, error_message)
    """
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()
        try:
            cur.execute('''
                SELECT id, lender, amount, currency, status
                FROM loans
                WHERE (id::text = %s OR loan_id = %s) AND borrower = %s
                ORDER BY id DESC LIMIT 1
            ''', (loan_id, loan_id, borrower))
        except Exception as e:
            if not _looks_like_missing_column(e):
                raise
            conn.rollback()
            cur = conn.cursor()
            cur.execute('''
                SELECT id, lender, amount, currency, status
                FROM loans
                WHERE id::text = %s AND borrower = %s
                ORDER BY id DESC LIMIT 1
            ''', (loan_id, borrower))
        result = cur.fetchone()
        if not result:
            return None, f"No loan {loan_id} found where you are the borrower."
        db_id, lender, amount, currency, status = result
        if status in ('repaid', 'refunded'):
            return None, "This loan is already closed and cannot be disputed."
        if status == 'disputed':
            return None, "This loan is already marked as disputed."
        cur.execute('''
            UPDATE loans SET status = 'disputed', last_updated = %s WHERE id = %s
        ''', (datetime.now(), db_id))
        conn.commit()
        logger.info(f"Loan {db_id} disputed by {borrower}")
        log_event("loan_disputed", actor=borrower, actor_role="borrower", target_user=lender,
                  loan_id=loan_id, source="service",
                  details={"amount": str(amount), "currency": currency})
        log_audit(borrower, "borrower", "dispute_opened", "loan", loan_id,
                  new_value={"lender": lender, "amount": str(amount), "currency": currency})
        add_loan_event(loan_id, "dispute_opened", borrower,
                       f"Borrower opened dispute — {amount} {currency}")
        # Notify lender of dispute
        create_notification(
            lender, "dispute_opened",
            "Dispute opened on your loan",
            f"u/{borrower} has opened a dispute on loan {loan_id} ({amount} {currency}). "
            "A moderator will review this. Check your dashboard for details.")
        return {"db_id": db_id, "lender": lender, "borrower": borrower,
                "amount": Decimal(amount), "currency": currency}, None
    except Exception as e:
        conn.rollback()
        logger.error(f"dispute_loan error: {e}", exc_info=True)
        return None, "Database error while flagging dispute."
    finally:
        cur.close()
        conn.close()


def get_lender_stats(lender: str):
    """
    Get lending stats for a specific lender.
    Returns (stats_dict, error_message).
    """
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT
                    COUNT(*)                                                    AS total,
                    COUNT(*) FILTER (WHERE status IN ('confirmed','partially_repaid')) AS active,
                    COUNT(*) FILTER (WHERE status = 'unpaid')                  AS unpaid,
                    COUNT(*) FILTER (WHERE status = 'repaid')                  AS repaid,
                    COALESCE(SUM(amount), 0)                                   AS total_lent,
                    COALESCE(SUM(amount_repaid), 0)                            AS total_recovered,
                    COALESCE(SUM(COALESCE(repay_amount, amount) - amount_repaid)
                        FILTER (WHERE status IN ('confirmed','partially_repaid','unpaid')), 0) AS outstanding
                FROM loans WHERE lender = %s
            """, (lender.lower(),))
        except Exception as e:
            if not _looks_like_missing_column(e):
                raise
            conn.rollback()
            cur.execute("""
                SELECT
                    COUNT(*)                                                    AS total,
                    COUNT(*) FILTER (WHERE status IN ('confirmed','partially_repaid')) AS active,
                    COUNT(*) FILTER (WHERE status = 'unpaid')                  AS unpaid,
                    COUNT(*) FILTER (WHERE status = 'repaid')                  AS repaid,
                    COALESCE(SUM(amount), 0)                                   AS total_lent,
                    COALESCE(SUM(amount_repaid), 0)                            AS total_recovered,
                    COALESCE(SUM(amount - amount_repaid)
                        FILTER (WHERE status IN ('confirmed','partially_repaid','unpaid')), 0) AS outstanding
                FROM loans WHERE lender = %s
            """, (lender.lower(),))
        row = cur.fetchone()
        return {
            "total_loans":      row[0],
            "active_loans":     row[1],
            "unpaid_loans":     row[2],
            "repaid_loans":     row[3],
            "total_lent":       row[4],
            "total_recovered":  row[5],
            "outstanding":      row[6],
        }, None
    except Exception as e:
        logger.error(f"get_lender_stats error: {e}", exc_info=True)
        return None, str(e)
    finally:
        cur.close()
        conn.close()


def run_integrity_checks():
    """
    Runs a set of DB-level sanity checks and returns a list of issues.
    Each issue is a dict: {check, severity, loan_id, lender, borrower, detail}
    severity: "error" | "warning"
    """
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    issues = []
    try:
        cur = conn.cursor()

        # Overpaid: amount_repaid > repay_amount
        cur.execute("""
            SELECT loan_id, lender, borrower, amount, repay_amount, amount_repaid, currency
            FROM loans
            WHERE amount_repaid > COALESCE(repay_amount, amount)
              AND status NOT IN ('refunded')
        """)
        for r in cur.fetchall():
            issues.append({"check": "Overpaid", "severity": "error",
                "loan_id": r[0], "lender": r[1], "borrower": r[2],
                "detail": f"repaid {r[5]} > repay_amount {r[4]} {r[6]}"})

        # Status repaid but remaining > 0
        cur.execute("""
            SELECT loan_id, lender, borrower, COALESCE(repay_amount, amount) - amount_repaid AS remaining, currency
            FROM loans
            WHERE status = 'repaid'
              AND COALESCE(repay_amount, amount) - amount_repaid > 0.01
        """)
        for r in cur.fetchall():
            issues.append({"check": "Repaid w/ balance", "severity": "warning",
                "loan_id": r[0], "lender": r[1], "borrower": r[2],
                "detail": f"{r[3]:.2f} {r[4]} still outstanding despite repaid status"})

        # Active loan with repay_date > 90 days overdue (no $unpaid filed)
        cur.execute("""
            SELECT loan_id, lender, borrower, repay_date, currency
            FROM loans
            WHERE status IN ('confirmed', 'partially_repaid')
              AND repay_date IS NOT NULL
              AND repay_date < NOW() - INTERVAL '90 days'
        """)
        for r in cur.fetchall():
            issues.append({"check": "90-day overdue", "severity": "warning",
                "loan_id": r[0], "lender": r[1], "borrower": r[2],
                "detail": f"due {r[3]}, still active — no $unpaid filed"})

        # Duplicate active loans same lender+borrower
        cur.execute("""
            SELECT lender, borrower, COUNT(*) AS cnt
            FROM loans
            WHERE status IN ('confirmed', 'partially_repaid')
            GROUP BY lender, borrower
            HAVING COUNT(*) > 1
        """)
        for r in cur.fetchall():
            issues.append({"check": "Duplicate active", "severity": "warning",
                "loan_id": None, "lender": r[0], "borrower": r[1],
                "detail": f"{r[2]} simultaneous active loans between same pair"})

        # Lenders in loans table not in user_roles
        cur.execute("""
            SELECT DISTINCT l.lender
            FROM loans l
            LEFT JOIN user_roles ur ON lower(l.lender) = lower(ur.username)
            WHERE ur.username IS NULL
        """)
        for r in cur.fetchall():
            issues.append({"check": "Unregistered lender", "severity": "warning",
                "loan_id": None, "lender": r[0], "borrower": None,
                "detail": "lender has loans but no role record"})

        # Borrowers in loans table not in user_roles
        cur.execute("""
            SELECT DISTINCT l.borrower
            FROM loans l
            LEFT JOIN user_roles ur ON lower(l.borrower) = lower(ur.username)
            WHERE ur.username IS NULL
        """)
        for r in cur.fetchall():
            issues.append({"check": "Unregistered borrower", "severity": "warning",
                "loan_id": None, "lender": None, "borrower": r[0],
                "detail": "borrower has loans but no role record"})

        cur.close()
        conn.close()
        return issues, None
    except Exception as e:
        logger.error(f"run_integrity_checks error: {e}", exc_info=True)
        return None, str(e)


# ---------------------------------------------------------------------------
# Borrower contact info + OTP auth
# ---------------------------------------------------------------------------

def set_borrower_contact(username: str, contact_email: str = None, contact_phone: str = None):
    """Update contact_email and/or contact_phone on a user_roles row."""
    conn = _get_db()
    if not conn:
        return False, "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE user_roles
               SET contact_email = COALESCE(%s, contact_email),
                   contact_phone = COALESCE(%s, contact_phone)
             WHERE lower(username) = lower(%s)
        """, (contact_email or None, contact_phone or None, username))
        if cur.rowcount == 0:
            cur.execute("""
                INSERT INTO user_roles (username, role, contact_email, contact_phone)
                VALUES (lower(%s), 'borrower', %s, %s)
                ON CONFLICT (username) DO UPDATE
                   SET contact_email = COALESCE(EXCLUDED.contact_email, user_roles.contact_email),
                       contact_phone = COALESCE(EXCLUDED.contact_phone, user_roles.contact_phone)
            """, (username, contact_email or None, contact_phone or None))
        conn.commit()
        return True, None
    except Exception as e:
        logger.error(f"set_borrower_contact error: {e}", exc_info=True)
        return False, str(e)
    finally:
        cur.close()
        conn.close()


def get_borrower_contact(username: str):
    """Return (email, phone) or (None, None) if not set."""
    conn = _get_db()
    if not conn:
        return None, None
    try:
        cur = conn.cursor()
        cur.execute("SELECT contact_email, contact_phone FROM user_roles WHERE lower(username) = lower(%s)", (username,))
        row = cur.fetchone()
        return (row[0], row[1]) if row else (None, None)
    except Exception:
        return None, None
    finally:
        cur.close()
        conn.close()


def _otp_hash(code: str) -> str:
    import hashlib
    return hashlib.sha256(code.encode()).hexdigest()


def create_borrower_otp(username: str, contact: str, contact_type: str):
    """
    Generate a 6-digit OTP, store hashed, return plaintext code.
    contact_type: 'email' | 'sms'
    """
    import random
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        code = f"{random.SystemRandom().randint(0, 999999):06d}"
        hashed = _otp_hash(code)
        cur = conn.cursor()
        # Invalidate previous unused OTPs for this user
        cur.execute("""
            UPDATE borrower_otp_sessions SET used = TRUE
            WHERE username = lower(%s) AND used = FALSE
        """, (username,))
        cur.execute("""
            INSERT INTO borrower_otp_sessions (username, otp_hash, contact, contact_type, expires_at)
            VALUES (lower(%s), %s, %s, %s, NOW() + INTERVAL '10 minutes')
        """, (username, hashed, contact, contact_type))
        conn.commit()
        return code, None
    except Exception as e:
        logger.error(f"create_borrower_otp error: {e}", exc_info=True)
        return None, str(e)
    finally:
        cur.close()
        conn.close()


def verify_borrower_otp(username: str, code: str):
    """
    Verify OTP. Returns (True, None) on success or (False, error_msg).
    Marks the OTP as used on success.
    """
    conn = _get_db()
    if not conn:
        return False, "Database connection failed."
    try:
        hashed = _otp_hash(code.strip())
        cur = conn.cursor()
        cur.execute("""
            SELECT id FROM borrower_otp_sessions
            WHERE lower(username) = lower(%s)
              AND otp_hash = %s
              AND used = FALSE
              AND expires_at > NOW()
            ORDER BY created_at DESC
            LIMIT 1
        """, (username, hashed))
        row = cur.fetchone()
        if not row:
            return False, "Invalid or expired code."
        cur.execute("UPDATE borrower_otp_sessions SET used = TRUE WHERE id = %s", (row[0],))
        conn.commit()
        return True, None
    except Exception as e:
        logger.error(f"verify_borrower_otp error: {e}", exc_info=True)
        return False, str(e)
    finally:
        cur.close()
        conn.close()


def verify_borrower_loan_claim(username: str, loan_id: str):
    """
    Check that loan_id exists and borrower matches username.
    Returns (True, None) or (False, error_msg).
    """
    conn = _get_db()
    if not conn:
        return False, "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 1 FROM loans
            WHERE (loan_id = %s OR CAST(id AS TEXT) = %s)
              AND lower(borrower) = lower(%s)
            LIMIT 1
        """, (loan_id, loan_id, username))
        found = cur.fetchone() is not None
        return found, None if found else "Loan ID not found for that username."
    except Exception as e:
        logger.error(f"verify_borrower_loan_claim error: {e}", exc_info=True)
        return False, str(e)
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Borrower magic link tokens (read-only dashboard)
# ---------------------------------------------------------------------------

def create_magic_link(username: str, days: int = 7):
    """
    Generate a signed magic link token for read-only borrower dashboard access.
    Returns (token_plaintext, None) or (None, error).
    Token is valid for `days` days and is single-use.
    """
    import hashlib, secrets as _sec
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        token = _sec.token_urlsafe(32)
        hashed = hashlib.sha256(token.encode()).hexdigest()
        cur = conn.cursor()
        # Expire any existing active tokens for this user
        cur.execute("""
            UPDATE borrower_magic_links SET used = TRUE
            WHERE lower(username) = lower(%s) AND used = FALSE
        """, (username,))
        cur.execute("""
            INSERT INTO borrower_magic_links (username, token_hash, expires_at)
            VALUES (lower(%s), %s, NOW() + (%s * INTERVAL '1 day'))
        """, (username, hashed, days))
        conn.commit()
        return token, None
    except Exception as e:
        logger.error(f"create_magic_link error: {e}", exc_info=True)
        return None, str(e)
    finally:
        cur.close()
        conn.close()


def validate_magic_link(token: str):
    """
    Validate a magic link token. Returns (username, None) or (None, error).
    Does NOT mark the token as used — read-only views may be revisited.
    """
    import hashlib
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        hashed = hashlib.sha256(token.encode()).hexdigest()
        cur = conn.cursor()
        cur.execute("""
            SELECT username FROM borrower_magic_links
            WHERE token_hash = %s AND used = FALSE AND expires_at > NOW()
            LIMIT 1
        """, (hashed,))
        row = cur.fetchone()
        if not row:
            return None, "Link is invalid or has expired."
        return row[0], None
    except Exception as e:
        logger.error(f"validate_magic_link error: {e}", exc_info=True)
        return None, str(e)
    finally:
        cur.close()
        conn.close()

# =============================================================================
# AUDIT LOGGING
# =============================================================================

def log_audit(actor_username: str, actor_role: str, action_type: str,
              target_type: str = None, target_id: str = None,
              old_value: dict = None, new_value: dict = None,
              ip_address: str = None, metadata: dict = None):
    """Write an audit log entry. Never raises."""
    conn = _get_db()
    if not conn:
        logger.warning("log_audit: no DB connection, skipping")
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO audit_logs
                (actor_username, actor_role, action_type, target_type, target_id,
                 old_value_json, new_value_json, ip_address, metadata_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            (actor_username or "system").lower(),
            actor_role or "unknown",
            action_type,
            target_type,
            str(target_id) if target_id is not None else None,
            json.dumps(old_value) if old_value is not None else None,
            json.dumps(new_value) if new_value is not None else None,
            ip_address,
            json.dumps(metadata) if metadata is not None else None,
        ))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"log_audit error: {e}", exc_info=True)
        return False
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


def get_audit_log(username: str = None, action_type: str = None,
                  target_type: str = None, target_id: str = None,
                  date_from: str = None, date_to: str = None,
                  limit: int = 50, offset: int = 0,
                  target_username: str = None, loan_id: str = None):
    """Fetch audit log entries with optional filters. Returns (rows, total, error)."""
    conn = _get_db()
    if not conn:
        return [], 0, "Database connection failed"
    try:
        cur = conn.cursor()
        clauses, params = [], []
        if username:
            clauses.append("lower(actor_username) = lower(%s)")
            params.append(username)
        if target_username:
            clauses.append("(target_type = 'user' AND lower(target_id) = lower(%s))")
            params.append(target_username)
        if loan_id:
            clauses.append("(target_type = 'loan' AND target_id = %s)")
            params.append(str(loan_id))
        if action_type:
            clauses.append("action_type = %s")
            params.append(action_type)
        if target_type:
            clauses.append("target_type = %s")
            params.append(target_type)
        if target_id:
            clauses.append("target_id = %s")
            params.append(str(target_id))
        if date_from:
            clauses.append("created_at >= %s::timestamptz")
            params.append(date_from)
        if date_to:
            clauses.append("created_at <= %s::timestamptz")
            params.append(date_to)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        cur.execute(f"SELECT COUNT(*) FROM audit_logs {where}", params)
        total = cur.fetchone()[0]
        cur.execute(f"""
            SELECT id, actor_username, actor_role, action_type, target_type,
                   target_id, old_value_json, new_value_json, ip_address,
                   metadata_json, created_at
            FROM audit_logs {where}
            ORDER BY created_at DESC LIMIT %s OFFSET %s
        """, params + [limit, offset])
        cols = ["id", "actor_username", "actor_role", "action_type", "target_type",
                "target_id", "old_value_json", "new_value_json", "ip_address",
                "metadata_json", "created_at"]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        for r in rows:
            r["created_at"] = r["created_at"].isoformat() if r["created_at"] else None
        return rows, total, None
    except Exception as e:
        logger.error(f"get_audit_log error: {e}", exc_info=True)
        return [], 0, str(e)
    finally:
        cur.close()
        conn.close()


# =============================================================================
# LOAN EVENT TIMELINE
# =============================================================================

def add_loan_event(loan_id: str, event_type: str, actor_username: str = None,
                   details: str = None):
    """Append an event to the loan timeline. Never raises."""
    conn = _get_db()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO loan_events (loan_id, event_type, actor_username, details)
            VALUES (%s, %s, %s, %s)
        """, (str(loan_id), event_type,
              (actor_username or "system").lower(), details))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"add_loan_event error: {e}", exc_info=True)
        return False
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


def get_loan_events(loan_id: str):
    """Return timeline events for a loan, newest first. Returns (list, error)."""
    conn = _get_db()
    if not conn:
        return [], "Database connection failed"
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, loan_id, event_type, actor_username, details, created_at
            FROM loan_events WHERE loan_id = %s ORDER BY created_at DESC
        """, (str(loan_id),))
        cols = ["id", "loan_id", "event_type", "actor_username", "details", "created_at"]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        for r in rows:
            r["created_at"] = r["created_at"].isoformat() if r["created_at"] else None
        return rows, None
    except Exception as e:
        logger.error(f"get_loan_events error: {e}", exc_info=True)
        return [], str(e)
    finally:
        cur.close()
        conn.close()


# =============================================================================
# NOTIFICATIONS
# =============================================================================

def create_notification(username: str, notification_type: str,
                        title: str, message: str):
    """Create an in-app notification for a user. Never raises."""
    conn = _get_db()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO notifications (username, notification_type, title, message)
            VALUES (lower(%s), %s, %s, %s)
        """, (username, notification_type, title, message))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"create_notification error: {e}", exc_info=True)
        return False
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


def get_notifications(username: str, unread_only: bool = False,
                      limit: int = 50, offset: int = 0):
    """Fetch notifications with pagination. Returns (list, unread_count, total, error)."""
    conn = _get_db()
    if not conn:
        return [], 0, 0, "Database connection failed"
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM notifications WHERE lower(username)=lower(%s) AND read=FALSE",
            (username,))
        unread_count = cur.fetchone()[0]
        read_clause = "AND read = FALSE" if unread_only else ""
        cur.execute(f"""
            SELECT COUNT(*) FROM notifications
            WHERE lower(username)=lower(%s) {read_clause}
        """, (username,))
        total = cur.fetchone()[0]
        cur.execute(f"""
            SELECT id, username, notification_type, title, message, read, created_at
            FROM notifications WHERE lower(username)=lower(%s) {read_clause}
            ORDER BY created_at DESC LIMIT %s OFFSET %s
        """, (username, limit, offset))
        cols = ["id", "username", "notification_type", "title", "message", "read", "created_at"]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        for r in rows:
            r["created_at"] = r["created_at"].isoformat() if r["created_at"] else None
        return rows, unread_count, total, None
    except Exception as e:
        logger.error(f"get_notifications error: {e}", exc_info=True)
        return [], 0, 0, str(e)
    finally:
        cur.close()
        conn.close()


def mark_notifications_read(username: str, notification_ids: list = None):
    """Mark notifications read. Pass None to mark all. Returns (ok, error)."""
    conn = _get_db()
    if not conn:
        return False, "Database connection failed"
    try:
        cur = conn.cursor()
        if notification_ids:
            cur.execute("""
                UPDATE notifications SET read=TRUE
                WHERE lower(username)=lower(%s) AND id=ANY(%s)
            """, (username, notification_ids))
        else:
            cur.execute(
                "UPDATE notifications SET read=TRUE WHERE lower(username)=lower(%s)",
                (username,))
        conn.commit()
        return True, None
    except Exception as e:
        logger.error(f"mark_notifications_read error: {e}", exc_info=True)
        return False, str(e)
    finally:
        cur.close()
        conn.close()


# =============================================================================
# VERIFIED LENDER
# =============================================================================

def set_verified_lender(username: str, verified: bool, granted_by: str,
                        note: str = None):
    """Set or revoke verified lender status. Returns (ok, error)."""
    conn = _get_db()
    if not conn:
        return False, "Database connection failed"
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO user_roles (username, role)
            VALUES (lower(%s), 'lender')
            ON CONFLICT (username) DO NOTHING
        """, (username,))
        if verified:
            cur.execute("""
                UPDATE user_roles
                SET verified_lender=TRUE, verified_lender_at=NOW(),
                    verified_lender_by=%s, verification_note=%s,
                    perm_version = COALESCE(perm_version, 0) + 1
                WHERE lower(username)=lower(%s)
            """, (granted_by, note, username))
        else:
            cur.execute("""
                UPDATE user_roles
                SET verified_lender=FALSE, verified_lender_by=%s, verification_note=%s,
                    perm_version = COALESCE(perm_version, 0) + 1
                WHERE lower(username)=lower(%s)
            """, (granted_by, note, username))
        conn.commit()
        return True, None
    except Exception as e:
        logger.error(f"set_verified_lender error: {e}", exc_info=True)
        return False, str(e)
    finally:
        cur.close()
        conn.close()


def get_verified_lender_status(username: str):
    """Returns (is_verified, details_dict, error)."""
    conn = _get_db()
    if not conn:
        return False, {}, "Database connection failed"
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT verified_lender, verified_lender_at, verified_lender_by,
                   verification_note, role
            FROM user_roles WHERE lower(username)=lower(%s)
        """, (username,))
        row = cur.fetchone()
        if not row:
            return False, {}, None
        return bool(row[0]), {
            "verified": bool(row[0]),
            "verified_at": row[1].isoformat() if row[1] else None,
            "verified_by": row[2],
            "note": row[3],
            "role": row[4],
        }, None
    except Exception as e:
        logger.error(f"get_verified_lender_status error: {e}", exc_info=True)
        return False, {}, str(e)
    finally:
        cur.close()
        conn.close()


# =============================================================================
# REDDIT USERNAME LINKING
# =============================================================================

def link_reddit_username(target_username: str, reddit_username: str, linked_by: str):
    """Link or update a Reddit username for a dashboard user. Prevents duplicate active links."""
    db = _get_db()
    if not db:
        return False, "Database connection failed"
    try:
        cur = db.cursor()
        # Normalise
        reddit_username = (reddit_username or "").strip().lower().lstrip("u/")
        if not reddit_username:
            return False, "reddit_username is required"
        # Check for duplicate — another user already has this reddit_username
        cur.execute(
            "SELECT username FROM user_roles WHERE lower(reddit_username)=lower(%s) AND lower(username)!=lower(%s)",
            (reddit_username, target_username)
        )
        conflict = cur.fetchone()
        if conflict:
            return False, f"Reddit username u/{reddit_username} is already linked to u/{conflict[0]}"
        cur.execute("""
            UPDATE user_roles
            SET reddit_username = %s,
                reddit_username_linked_at = NOW(),
                reddit_username_linked_by = %s
            WHERE lower(username) = lower(%s)
        """, (reddit_username, linked_by, target_username))
        if cur.rowcount == 0:
            # User doesn't exist in user_roles yet — insert a minimal row
            cur.execute("""
                INSERT INTO user_roles (username, role, reddit_username, reddit_username_linked_at, reddit_username_linked_by)
                VALUES (%s, 'borrower', %s, NOW(), %s)
                ON CONFLICT (username) DO UPDATE SET
                    reddit_username = EXCLUDED.reddit_username,
                    reddit_username_linked_at = EXCLUDED.reddit_username_linked_at,
                    reddit_username_linked_by = EXCLUDED.reddit_username_linked_by
            """, (target_username.lower(), reddit_username, linked_by))
        db.commit()
        return True, None
    except Exception as e:
        db.rollback()
        return False, str(e)
    finally:
        try: cur.close()
        except: pass
        db.close()


def unlink_reddit_username(target_username: str, linked_by: str):
    """Remove the Reddit username link for a dashboard user."""
    db = _get_db()
    if not db:
        return False, "Database connection failed"
    try:
        cur = db.cursor()
        cur.execute("""
            UPDATE user_roles
            SET reddit_username = NULL,
                reddit_username_linked_at = NULL,
                reddit_username_linked_by = NULL
            WHERE lower(username) = lower(%s)
        """, (target_username,))
        db.commit()
        return True, None
    except Exception as e:
        db.rollback()
        return False, str(e)
    finally:
        try: cur.close()
        except: pass
        db.close()


def get_reddit_username(target_username: str):
    """Return (reddit_username, linked_at, linked_by) or (None, None, None)."""
    db = _get_db()
    if not db:
        return None, None, None
    try:
        cur = db.cursor()
        cur.execute("""
            SELECT reddit_username, reddit_username_linked_at, reddit_username_linked_by
            FROM user_roles WHERE lower(username) = lower(%s)
        """, (target_username,))
        row = cur.fetchone()
        if not row:
            return None, None, None
        return row[0], row[1], row[2]
    except Exception:
        return None, None, None
    finally:
        try: cur.close()
        except: pass
        db.close()


# =============================================================================
# GLOBAL SEARCH
# =============================================================================

def global_search(query: str, search_type: str = "all",
                  status_filter: str = None, limit: int = 50, offset: int = 0):
    """
    Search loans and users. search_type: 'all'|'loans'|'users'
    Returns (results_dict, total, error). results_dict keys: 'loans', 'users'
    """
    conn = _get_db()
    if not conn:
        return {}, 0, "Database connection failed"
    try:
        cur = conn.cursor()
        q = (query or "").strip().lower()
        results = {"loans": [], "users": [], "verifications": []}
        total = 0

        KNOWN_STATUSES = {"confirmed", "partially_repaid", "repaid", "unpaid",
                          "refunded", "disputed"}

        if search_type in ("all", "loans"):
            clauses, params = [], []
            if q in KNOWN_STATUSES and not status_filter:
                # Query is a status keyword — return loans in that status
                status_filter = q
                q_loans = ""
            else:
                q_loans = q
            if q_loans:
                clauses.append(
                    "(lower(loan_id) LIKE %s OR lower(lender) LIKE %s"
                    " OR lower(borrower) LIKE %s OR lower(COALESCE(notes,'')) LIKE %s)")
                like = f"%{q_loans}%"
                params += [like, like, like, like]
            if status_filter:
                clauses.append("status = %s")
                params.append(status_filter)
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            cur.execute(f"""
                SELECT loan_id, lender, borrower, amount, currency, status,
                       repay_date, date_created
                FROM loans {where} ORDER BY date_created DESC LIMIT %s OFFSET %s
            """, params + [limit, offset])
            cols = ["loan_id", "lender", "borrower", "amount", "currency",
                    "status", "repay_date", "created_at"]
            loans = [dict(zip(cols, r)) for r in cur.fetchall()]
            for r in loans:
                r["amount"] = float(r["amount"]) if r["amount"] else 0
                r["repay_date"] = str(r["repay_date"]) if r["repay_date"] else None
                r["created_at"] = r["created_at"].isoformat() if r["created_at"] else None
            results["loans"] = loans
            total += len(loans)

        if search_type in ("all", "users"):
            clauses, params = [], []
            if q:
                clauses.append("lower(username) LIKE %s")
                params.append(f"%{q}%")
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            # Also match on reddit_username if query provided
            if q:
                clauses[-1] = ("(lower(username) LIKE %s OR lower(COALESCE(reddit_username,'')) LIKE %s)")
                params[-1] = f"%{q}%"
                params.append(f"%{q}%")
                where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            cur.execute(f"""
                SELECT username, role, verified_lender, last_login, reddit_username
                FROM user_roles {where} ORDER BY username LIMIT %s OFFSET %s
            """, params + [min(limit, 25), offset])
            cols = ["username", "role", "verified_lender", "last_login", "reddit_username"]
            users = [dict(zip(cols, r)) for r in cur.fetchall()]
            for r in users:
                r["last_login"] = r["last_login"].isoformat() if r["last_login"] else None
                r["verified_lender"] = bool(r.get("verified_lender"))
            results["users"] = users
            total += len(users)

        if search_type in ("all", "verifications"):
            clauses, params = [], []
            if q in ("pending", "approved", "denied", "more_info"):
                clauses.append("va.status = %s")
                params.append(q)
            elif q:
                clauses.append(
                    "(lower(va.username) LIKE %s"
                    " OR lower(COALESCE(ur.reddit_username,'')) LIKE %s)")
                like = f"%{q}%"
                params += [like, like]
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            # Public fields only — never expose private_note in search results
            cur.execute(f"""
                SELECT va.id, va.username, va.requested_role, va.status,
                       va.reviewer, va.submitted_at, ur.reddit_username
                FROM verification_applications va
                LEFT JOIN user_roles ur ON lower(va.username) = lower(ur.username)
                {where} ORDER BY va.submitted_at DESC LIMIT %s OFFSET %s
            """, params + [min(limit, 25), offset])
            cols = ["id", "username", "requested_role", "status", "reviewer",
                    "submitted_at", "reddit_username"]
            verifications = [dict(zip(cols, r)) for r in cur.fetchall()]
            for r in verifications:
                r["submitted_at"] = r["submitted_at"].isoformat() if r["submitted_at"] else None
            results["verifications"] = verifications
            total += len(verifications)

        return results, total, None
    except Exception as e:
        logger.error(f"global_search error: {e}", exc_info=True)
        return {}, 0, str(e)
    finally:
        cur.close()
        conn.close()


# =============================================================================
# ADMIN: LENDER DIRECTORY + EXPANDED PROFILES (Sprint 6)
# =============================================================================

def list_lenders(verified_filter: str = None, has_reddit: bool = None,
                 q: str = None, limit: int = 200, offset: int = 0):
    """
    Admin lender directory. Includes users with role 'lender', verified
    lenders, verification applicants, and anyone who has funded a loan.
    verified_filter: 'verified' | 'unverified' | 'revoked' | None
    Returns (rows, total, error). Never exposes verification private notes.
    """
    conn = _get_db()
    if not conn:
        return [], 0, "Database connection failed"
    try:
        cur = conn.cursor()
        clauses = ["""(
            ur.role = 'lender'
            OR ur.verified_lender = TRUE
            OR ur.verified_lender_at IS NOT NULL
            OR ls.lender IS NOT NULL
            OR EXISTS (SELECT 1 FROM verification_applications va
                       WHERE lower(va.username) = lower(ur.username))
        )"""]
        params = []
        if verified_filter == "verified":
            clauses.append("ur.verified_lender = TRUE")
        elif verified_filter == "unverified":
            clauses.append("(ur.verified_lender IS NOT TRUE AND ur.verified_lender_at IS NULL)")
        elif verified_filter == "revoked":
            clauses.append("(ur.verified_lender IS NOT TRUE AND ur.verified_lender_at IS NOT NULL)")
        if has_reddit is True:
            clauses.append("ur.reddit_username IS NOT NULL")
        elif has_reddit is False:
            clauses.append("ur.reddit_username IS NULL")
        if q:
            clauses.append("(lower(ur.username) LIKE %s OR lower(COALESCE(ur.reddit_username,'')) LIKE %s)")
            like = f"%{q.strip().lower()}%"
            params += [like, like]
        where = "WHERE " + " AND ".join(clauses)
        base = f"""
            FROM user_roles ur
            LEFT JOIN (
                SELECT lower(lender) AS lender,
                       COUNT(*) AS total_loans,
                       COUNT(*) FILTER (WHERE status IN ('confirmed','partially_repaid')) AS active_loans,
                       COUNT(*) FILTER (WHERE status = 'repaid')   AS repaid_loans,
                       COUNT(*) FILTER (WHERE status = 'unpaid')   AS unpaid_loans,
                       COUNT(*) FILTER (WHERE status = 'disputed') AS disputed_loans,
                       COALESCE(SUM(amount), 0) AS total_funded
                FROM loans GROUP BY lower(lender)
            ) ls ON lower(ur.username) = ls.lender
            {where}
        """
        cur.execute(f"SELECT COUNT(*) {base}", params)
        total = cur.fetchone()[0]
        cur.execute(f"""
            SELECT ur.username, ur.role, ur.reddit_username, ur.verified_lender,
                   ur.verified_lender_at, ur.verified_lender_by, ur.last_login,
                   COALESCE(ls.total_loans, 0), COALESCE(ls.active_loans, 0),
                   COALESCE(ls.repaid_loans, 0), COALESCE(ls.unpaid_loans, 0),
                   COALESCE(ls.disputed_loans, 0), COALESCE(ls.total_funded, 0)
            {base}
            ORDER BY ur.verified_lender DESC, COALESCE(ls.total_loans, 0) DESC, ur.username
            LIMIT %s OFFSET %s
        """, params + [limit, offset])
        cols = ["username", "role", "reddit_username", "verified_lender",
                "verified_lender_at", "verified_lender_by", "last_login",
                "total_loans", "active_loans", "repaid_loans", "unpaid_loans",
                "disputed_loans", "total_funded"]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        for r in rows:
            r["verified_lender"] = bool(r["verified_lender"])
            r["verified_lender_at"] = r["verified_lender_at"].isoformat() if r["verified_lender_at"] else None
            r["last_login"] = r["last_login"].isoformat() if r["last_login"] else None
            r["total_funded"] = float(r["total_funded"]) if r["total_funded"] else 0.0
        return rows, total, None
    except Exception as e:
        logger.error(f"list_lenders error: {e}", exc_info=True)
        return [], 0, str(e)
    finally:
        cur.close()
        conn.close()


def get_admin_user_profile(username: str):
    """
    Full operational profile for the admin panel. Includes identity fields,
    loan counts by status (as lender and as borrower), amounts, recent loan
    events, and recent audit logs. Admin/mod use only — callers must enforce
    access control. Does NOT include verification private notes or contact info.
    Returns (profile_dict, error).
    """
    conn = _get_db()
    if not conn:
        return None, "Database connection failed"
    try:
        cur = conn.cursor()
        uname = username.lower()

        cur.execute("""
            SELECT username, role, reddit_username, verified_lender,
                   verified_lender_at, verified_lender_by,
                   COALESCE(perm_version, 0), created_at, last_login
            FROM user_roles WHERE lower(username) = lower(%s)
        """, (uname,))
        ident = cur.fetchone()

        # Loan counts by status, both directions
        profile = {
            "username": uname,
            "role": ident[1] if ident else None,
            "reddit_username": ident[2] if ident else None,
            "verified_lender": bool(ident[3]) if ident else False,
            "verified_lender_at": ident[4].isoformat() if ident and ident[4] else None,
            "verified_lender_by": ident[5] if ident else None,
            "perm_version": ident[6] if ident else 0,
            "created_at": ident[7].isoformat() if ident and ident[7] else None,
            "last_login": ident[8].isoformat() if ident and ident[8] else None,
        }

        for direction, col in (("lender", "lender"), ("borrower", "borrower")):
            cur.execute(f"""
                SELECT status, COUNT(*), COALESCE(SUM(amount), 0)
                FROM loans WHERE lower({col}) = lower(%s)
                GROUP BY status
            """, (uname,))
            by_status = {}
            total_amount = Decimal("0")
            total_count = 0
            for status, cnt, amt in cur.fetchall():
                by_status[status] = cnt
                total_count += cnt
                total_amount += Decimal(str(amt))
            profile[f"loans_as_{direction}_by_status"] = by_status
            profile[f"loans_as_{direction}_total"] = total_count
            key = "total_amount_funded" if direction == "lender" else "total_amount_borrowed"
            profile[key] = float(total_amount)

        # Outstanding (both directions, active/unpaid loans)
        try:
            cur.execute("""
                SELECT
                    COALESCE(SUM(COALESCE(repay_amount, amount) - amount_repaid)
                        FILTER (WHERE lower(lender) = lower(%s)), 0),
                    COALESCE(SUM(COALESCE(repay_amount, amount) - amount_repaid)
                        FILTER (WHERE lower(borrower) = lower(%s)), 0)
                FROM loans
                WHERE status IN ('confirmed', 'partially_repaid', 'unpaid')
                  AND (lower(lender) = lower(%s) OR lower(borrower) = lower(%s))
            """, (uname, uname, uname, uname))
            out_row = cur.fetchone()
        except Exception as e:
            if not _looks_like_missing_column(e):
                raise
            conn.rollback()
            cur.execute("""
                SELECT
                    COALESCE(SUM(amount - amount_repaid)
                        FILTER (WHERE lower(lender) = lower(%s)), 0),
                    COALESCE(SUM(amount - amount_repaid)
                        FILTER (WHERE lower(borrower) = lower(%s)), 0)
                FROM loans
                WHERE status IN ('confirmed', 'partially_repaid', 'unpaid')
                  AND (lower(lender) = lower(%s) OR lower(borrower) = lower(%s))
            """, (uname, uname, uname, uname))
            out_row = cur.fetchone()
        profile["outstanding_as_lender"] = float(out_row[0]) if out_row else 0.0
        profile["outstanding_as_borrower"] = float(out_row[1]) if out_row else 0.0

        # Recent loan events where user acted or on the user's loans
        cur.execute("""
            SELECT le.loan_id, le.event_type, le.actor_username, le.details, le.created_at
            FROM loan_events le
            WHERE lower(COALESCE(le.actor_username, '')) = lower(%s)
               OR le.loan_id IN (
                    SELECT loan_id FROM loans
                    WHERE lower(lender) = lower(%s) OR lower(borrower) = lower(%s))
            ORDER BY le.created_at DESC LIMIT 20
        """, (uname, uname, uname))
        profile["recent_loan_events"] = [
            {"loan_id": r[0], "event_type": r[1], "actor_username": r[2],
             "details": r[3],
             "created_at": r[4].isoformat() if r[4] else None}
            for r in cur.fetchall()]

        # Recent audit logs where user is actor or target
        cur.execute("""
            SELECT id, actor_username, actor_role, action_type, target_type,
                   target_id, created_at
            FROM audit_logs
            WHERE lower(actor_username) = lower(%s)
               OR (target_type = 'user' AND lower(target_id) = lower(%s))
            ORDER BY created_at DESC LIMIT 20
        """, (uname, uname))
        profile["recent_audit_logs"] = [
            {"id": r[0], "actor_username": r[1], "actor_role": r[2],
             "action_type": r[3], "target_type": r[4], "target_id": r[5],
             "created_at": r[6].isoformat() if r[6] else None}
            for r in cur.fetchall()]

        # Verification applications (public fields only — no private_note)
        cur.execute("""
            SELECT id, requested_role, status, reviewer, submitted_at, reviewed_at
            FROM verification_applications
            WHERE lower(username) = lower(%s)
            ORDER BY submitted_at DESC LIMIT 10
        """, (uname,))
        profile["verification_applications"] = [
            {"id": r[0], "requested_role": r[1], "status": r[2], "reviewer": r[3],
             "submitted_at": r[4].isoformat() if r[4] else None,
             "reviewed_at": r[5].isoformat() if r[5] else None}
            for r in cur.fetchall()]

        return profile, None
    except Exception as e:
        logger.error(f"get_admin_user_profile error: {e}", exc_info=True)
        return None, "Database error fetching admin profile."
    finally:
        cur.close()
        conn.close()


# =============================================================================
# PLATFORM METRICS (Sprint 7)
# =============================================================================

def get_platform_metrics():
    """
    Single-query platform summary for the admin metrics dashboard.
    Returns (metrics_dict, error).
    """
    conn = _get_db()
    if not conn:
        return None, "Database connection failed"
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                COUNT(*)                                                           AS total_loans,
                COUNT(*) FILTER (WHERE status IN ('confirmed','partially_repaid')) AS active_loans,
                COUNT(*) FILTER (WHERE status = 'repaid')                          AS repaid_loans,
                COUNT(*) FILTER (WHERE status = 'unpaid')                          AS unpaid_loans,
                COUNT(*) FILTER (WHERE status = 'disputed')                        AS disputed_loans,
                COUNT(*) FILTER (WHERE status = 'refunded')                        AS refunded_loans
            FROM loans
        """)
        loan_row = cur.fetchone()

        cur.execute("""
            SELECT
                COUNT(*)                                              AS total_users,
                COUNT(*) FILTER (WHERE role = 'lender')              AS total_lenders,
                COUNT(*) FILTER (WHERE role = 'borrower')            AS total_borrowers,
                COUNT(*) FILTER (WHERE role = 'mod')                 AS total_mods,
                COUNT(*) FILTER (WHERE verified_lender = TRUE)       AS verified_lenders
            FROM user_roles
        """)
        user_row = cur.fetchone()

        cur.execute("""
            SELECT COUNT(*) FROM verification_applications WHERE status = 'pending'
        """)
        pending_verif = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*) FROM notifications WHERE read = FALSE
        """)
        unread_notifs = cur.fetchone()[0]

        return {
            "loans": {
                "total":    loan_row[0],
                "active":   loan_row[1],
                "repaid":   loan_row[2],
                "unpaid":   loan_row[3],
                "disputed": loan_row[4],
                "refunded": loan_row[5],
            },
            "users": {
                "total":            user_row[0],
                "lenders":          user_row[1],
                "borrowers":        user_row[2],
                "mods":             user_row[3],
                "verified_lenders": user_row[4],
            },
            "verifications": {
                "pending": pending_verif,
            },
            "notifications": {
                "unread_system": unread_notifs,
            },
        }, None
    except Exception as e:
        logger.error(f"get_platform_metrics error: {e}", exc_info=True)
        return None, str(e)
    finally:
        cur.close()
        conn.close()


# =============================================================================
# NOTIFICATION RETENTION (Sprint 7)
# =============================================================================

def purge_old_notifications(days: int = 90):
    """
    Delete read notifications older than `days` days.
    Unread notifications are never purged automatically.
    Returns (deleted_count, error).
    """
    conn = _get_db()
    if not conn:
        return 0, "Database connection failed"
    try:
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM notifications
            WHERE read = TRUE
              AND created_at < NOW() - (%s || ' days')::INTERVAL
        """, (str(days),))
        deleted = cur.rowcount
        conn.commit()
        return deleted, None
    except Exception as e:
        logger.error(f"purge_old_notifications error: {e}", exc_info=True)
        return 0, str(e)
    finally:
        cur.close()
        conn.close()


# =============================================================================
# SPRINT 8 — FEEDBACK, NOTIFICATION PREFERENCES, EXPANDED METRICS, ANALYTICS
# =============================================================================

# ---------------------------------------------------------------------------
# Feedback submissions
# ---------------------------------------------------------------------------

FEEDBACK_CATEGORIES = {"bug", "suggestion", "feature_request"}
FEEDBACK_STATUSES   = {"open", "reviewed", "completed", "duplicate"}


def create_feedback(username: str, category: str, title: str, description: str):
    """Insert a feedback submission. Returns (feedback_id, error)."""
    if category not in FEEDBACK_CATEGORIES:
        return None, f"Invalid category '{category}'"
    title = title.strip()[:200]
    description = description.strip()[:2000]
    if not title:
        return None, "Title is required"
    if not description:
        return None, "Description is required"
    conn = _get_db()
    if not conn:
        return None, "Database connection failed"
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO feedback_submissions (username, category, title, description)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (username, category, title, description))
        row = cur.fetchone()
        conn.commit()
        return row[0], None
    except Exception as e:
        logger.error(f"create_feedback error: {e}", exc_info=True)
        return None, str(e)
    finally:
        cur.close()
        conn.close()


def get_feedback_list(status: str = None, category: str = None, username: str = None,
                      limit: int = 100, offset: int = 0):
    """Return paginated feedback submissions with optional filters. Returns (list, total, error)."""
    conn = _get_db()
    if not conn:
        return [], 0, "Database connection failed"
    try:
        cur = conn.cursor()
        conditions = []
        params = []
        if status:
            conditions.append("status = %s")
            params.append(status)
        if category:
            conditions.append("category = %s")
            params.append(category)
        if username:
            conditions.append("username = %s")
            params.append(username)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        cur.execute(f"SELECT COUNT(*) FROM feedback_submissions {where}", params)
        total = cur.fetchone()[0]
        cur.execute(f"""
            SELECT id, username, category, title, description, status,
                   reviewed_by, reviewer_note, created_at, updated_at
            FROM feedback_submissions {where}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, params + [limit, offset])
        rows = cur.fetchall()
        cols = ["id", "username", "category", "title", "description", "status",
                "reviewed_by", "reviewer_note", "created_at", "updated_at"]
        result = [dict(zip(cols, r)) for r in rows]
        for item in result:
            for k in ("created_at", "updated_at"):
                if item[k]:
                    item[k] = item[k].isoformat()
        return result, total, None
    except Exception as e:
        logger.error(f"get_feedback_list error: {e}", exc_info=True)
        return [], 0, str(e)
    finally:
        cur.close()
        conn.close()


def update_feedback_status(feedback_id: int, status: str, reviewed_by: str,
                           reviewer_note: str = None):
    """Update feedback status. Returns (success, error)."""
    if status not in FEEDBACK_STATUSES:
        return False, f"Invalid status '{status}'"
    conn = _get_db()
    if not conn:
        return False, "Database connection failed"
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE feedback_submissions
            SET status = %s, reviewed_by = %s, reviewer_note = %s,
                updated_at = NOW()
            WHERE id = %s
        """, (status, reviewed_by, reviewer_note, feedback_id))
        if cur.rowcount == 0:
            return False, "Feedback not found"
        conn.commit()
        return True, None
    except Exception as e:
        logger.error(f"update_feedback_status error: {e}", exc_info=True)
        return False, str(e)
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Notification preferences
# ---------------------------------------------------------------------------

_NOTIF_PREF_DEFAULTS = {
    "due_date_reminders": True,
    "status_updates": True,
    "verification_updates": True,
    "dispute_updates": True,
}


def get_notification_preferences(username: str):
    """Return preferences dict for a user, falling back to defaults. Returns (prefs, error)."""
    conn = _get_db()
    if not conn:
        return dict(_NOTIF_PREF_DEFAULTS), "Database connection failed"
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT due_date_reminders, status_updates, verification_updates, dispute_updates
            FROM notification_preferences WHERE username = %s
        """, (username,))
        row = cur.fetchone()
        if not row:
            return dict(_NOTIF_PREF_DEFAULTS), None
        return {
            "due_date_reminders": row[0],
            "status_updates": row[1],
            "verification_updates": row[2],
            "dispute_updates": row[3],
        }, None
    except Exception as e:
        logger.error(f"get_notification_preferences error: {e}", exc_info=True)
        return dict(_NOTIF_PREF_DEFAULTS), str(e)
    finally:
        cur.close()
        conn.close()


def update_notification_preferences(username: str, due_date_reminders: bool,
                                    status_updates: bool, verification_updates: bool,
                                    dispute_updates: bool):
    """Upsert notification preferences. Returns (success, error)."""
    conn = _get_db()
    if not conn:
        return False, "Database connection failed"
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO notification_preferences
                (username, due_date_reminders, status_updates, verification_updates,
                 dispute_updates, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (username) DO UPDATE SET
                due_date_reminders   = EXCLUDED.due_date_reminders,
                status_updates       = EXCLUDED.status_updates,
                verification_updates = EXCLUDED.verification_updates,
                dispute_updates      = EXCLUDED.dispute_updates,
                updated_at           = NOW()
        """, (username, due_date_reminders, status_updates, verification_updates,
              dispute_updates))
        conn.commit()
        return True, None
    except Exception as e:
        logger.error(f"update_notification_preferences error: {e}", exc_info=True)
        return False, str(e)
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Expanded platform metrics (Sprint 8)
# ---------------------------------------------------------------------------

def get_expanded_metrics():
    """
    Extends base metrics with monthly activity, active-user counts,
    verification monthly stats, disputes, and feedback summary.
    Returns (metrics_dict, error).
    """
    conn = _get_db()
    if not conn:
        return None, "Database connection failed"
    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT
                COUNT(*)                                                           AS total_loans,
                COUNT(*) FILTER (WHERE status IN ('confirmed','partially_repaid')) AS active_loans,
                COUNT(*) FILTER (WHERE status = 'repaid')                          AS repaid_loans,
                COUNT(*) FILTER (WHERE status = 'unpaid')                          AS unpaid_loans,
                COUNT(*) FILTER (WHERE status = 'disputed')                        AS disputed_loans,
                COUNT(*) FILTER (WHERE status = 'refunded')                        AS refunded_loans,
                COUNT(*) FILTER (WHERE date_created >= DATE_TRUNC('month', NOW())) AS loans_this_month,
                COUNT(*) FILTER (WHERE status = 'repaid'
                    AND last_updated >= DATE_TRUNC('month', NOW()))                 AS repayments_this_month
            FROM loans
        """)
        loan_row = cur.fetchone()

        cur.execute("""
            SELECT
                COUNT(*)                                              AS total_users,
                COUNT(*) FILTER (WHERE role = 'lender')              AS total_lenders,
                COUNT(*) FILTER (WHERE role = 'borrower')            AS total_borrowers,
                COUNT(*) FILTER (WHERE role = 'mod')                 AS total_mods,
                COUNT(*) FILTER (WHERE verified_lender = TRUE)       AS verified_lenders,
                COUNT(*) FILTER (WHERE role = 'lender'
                    AND last_login >= NOW() - INTERVAL '30 days')    AS active_lenders,
                COUNT(*) FILTER (WHERE role = 'borrower'
                    AND last_login >= NOW() - INTERVAL '30 days')    AS active_borrowers
            FROM user_roles
        """)
        user_row = cur.fetchone()

        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'pending')                          AS pending,
                COUNT(*) FILTER (WHERE status = 'approved'
                    AND reviewed_at >= DATE_TRUNC('month', NOW()))                  AS approvals_this_month,
                COUNT(*) FILTER (WHERE status = 'denied'
                    AND reviewed_at >= DATE_TRUNC('month', NOW()))                  AS denials_this_month
            FROM verification_applications
        """)
        verif_row = cur.fetchone()

        cur.execute("SELECT COUNT(*) FROM notifications WHERE read = FALSE")
        unread_notifs = cur.fetchone()[0]

        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'open')              AS open_feedback,
                COUNT(*) FILTER (WHERE category = 'bug')             AS bugs,
                COUNT(*) FILTER (WHERE category = 'suggestion')      AS suggestions,
                COUNT(*) FILTER (WHERE category = 'feature_request') AS features,
                COUNT(*)                                              AS total
            FROM feedback_submissions
        """)
        fb_row = cur.fetchone()

        return {
            "loans": {
                "total":    loan_row[0],
                "active":   loan_row[1],
                "repaid":   loan_row[2],
                "unpaid":   loan_row[3],
                "disputed": loan_row[4],
                "refunded": loan_row[5],
                "created_this_month":    loan_row[6],
                "repayments_this_month": loan_row[7],
            },
            "users": {
                "total":            user_row[0],
                "lenders":          user_row[1],
                "borrowers":        user_row[2],
                "mods":             user_row[3],
                "verified_lenders": user_row[4],
                "active_lenders":   user_row[5],
                "active_borrowers": user_row[6],
            },
            "verifications": {
                "pending":              verif_row[0],
                "approvals_this_month": verif_row[1],
                "denials_this_month":   verif_row[2],
            },
            "disputes": {
                "active": loan_row[4],
            },
            "notifications": {
                "unread_system": unread_notifs,
            },
            "feedback": {
                "open":        fb_row[0],
                "bugs":        fb_row[1],
                "suggestions": fb_row[2],
                "features":    fb_row[3],
                "total":       fb_row[4],
            },
        }, None
    except Exception as e:
        logger.error(f"get_expanded_metrics error: {e}", exc_info=True)
        return None, str(e)
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# User activity timeline (for audit investigations)
# ---------------------------------------------------------------------------

def get_user_activity_timeline(username: str, limit: int = 50):
    """
    Return a unified activity feed for a user across audit_logs, loan_events,
    and verification_applications — merged and sorted by date.
    Returns (events_list, error).
    """
    conn = _get_db()
    if not conn:
        return [], "Database connection failed"
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 'audit' AS source, action_type AS event_type,
                   actor_username AS actor, created_at,
                   COALESCE(target_id, '') AS ref,
                   COALESCE(new_value_json, '') AS detail
            FROM audit_logs
            WHERE actor_username = %s OR target_id = %s
            UNION ALL
            SELECT 'loan_event', event_type, actor_username, created_at,
                   loan_id, COALESCE(details, '')
            FROM loan_events
            WHERE actor_username = %s
            UNION ALL
            SELECT 'verification', status, username, submitted_at,
                   CAST(id AS TEXT), COALESCE(public_note, '')
            FROM verification_applications
            WHERE username = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (username, username, username, username, limit))
        rows = cur.fetchall()
        cols = ["source", "event_type", "actor", "created_at", "ref", "detail"]
        result = [dict(zip(cols, r)) for r in rows]
        for ev in result:
            if ev["created_at"]:
                ev["created_at"] = ev["created_at"].isoformat()
        return result, None
    except Exception as e:
        logger.error(f"get_user_activity_timeline error: {e}", exc_info=True)
        return [], str(e)
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Beta analytics
# ---------------------------------------------------------------------------

def log_analytics_event(username: str, event_type: str, page: str = None,
                         metadata: dict = None):
    """
    Log a lightweight operational analytics event.
    Silently swallows errors so analytics never breaks user flows.
    """
    import json as _json
    conn = _get_db()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO analytics_events (username, event_type, page, metadata)
            VALUES (%s, %s, %s, %s)
        """, (username, event_type, page,
              _json.dumps(metadata) if metadata else None))
        conn.commit()
    except Exception as e:
        logger.warning(f"log_analytics_event swallowed: {e}")
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


def get_analytics_summary(days: int = 30):
    """
    Return operational analytics summary for the admin dashboard.
    Returns (summary_dict, error).
    """
    conn = _get_db()
    if not conn:
        return None, "Database connection failed"
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT event_type, COUNT(*) AS cnt
            FROM analytics_events
            WHERE created_at >= NOW() - (%s || ' days')::INTERVAL
            GROUP BY event_type
            ORDER BY cnt DESC
        """, (str(days),))
        by_type = {r[0]: r[1] for r in cur.fetchall()}

        cur.execute("""
            SELECT page, COUNT(*) AS cnt
            FROM analytics_events
            WHERE event_type = 'page_view'
              AND created_at >= NOW() - (%s || ' days')::INTERVAL
              AND page IS NOT NULL
            GROUP BY page
            ORDER BY cnt DESC
            LIMIT 10
        """, (str(days),))
        top_pages = [{"page": r[0], "views": r[1]} for r in cur.fetchall()]

        cur.execute("""
            SELECT COUNT(DISTINCT username)
            FROM analytics_events
            WHERE created_at >= NOW() - (%s || ' days')::INTERVAL
              AND username IS NOT NULL
        """, (str(days),))
        unique_users = cur.fetchone()[0]

        return {
            "period_days": days,
            "by_event_type": by_type,
            "top_pages": top_pages,
            "unique_active_users": unique_users,
        }, None
    except Exception as e:
        logger.error(f"get_analytics_summary error: {e}", exc_info=True)
        return None, str(e)
    finally:
        cur.close()
        conn.close()


# =============================================================================
# SPRINT 10 — MOD QUEUE, COMMUNITY HEALTH, ANNOUNCEMENTS, INVESTIGATION TOOLS
# =============================================================================

# ---------------------------------------------------------------------------
# Moderator work queue
# ---------------------------------------------------------------------------

def get_mod_queue():
    """
    Return a unified queue of items needing moderator attention:
    pending verifications, disputed loans, and open feedback.
    Returns (queue_dict, error).
    """
    conn = _get_db()
    if not conn:
        return None, "Database connection failed"
    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT id, username, requested_role, public_note, submitted_at
            FROM verification_applications
            WHERE status = 'pending'
            ORDER BY submitted_at ASC
            LIMIT 50
        """)
        rows = cur.fetchall()
        verif_cols = ["id", "username", "requested_role", "public_note", "submitted_at"]
        verifications = [dict(zip(verif_cols, r)) for r in rows]
        for v in verifications:
            if v["submitted_at"]:
                v["submitted_at"] = v["submitted_at"].isoformat()

        cur.execute("""
            SELECT loan_id, lender, borrower, amount, currency, date_created
            FROM loans
            WHERE status = 'disputed'
            ORDER BY date_created ASC
            LIMIT 50
        """)
        rows = cur.fetchall()
        dispute_cols = ["loan_id", "lender", "borrower", "amount", "currency", "date_created"]
        disputes = [dict(zip(dispute_cols, r)) for r in rows]
        for d in disputes:
            if d["date_created"]:
                d["date_created"] = d["date_created"].isoformat()
            d["amount"] = str(d["amount"])

        cur.execute("""
            SELECT id, username, category, title, created_at
            FROM feedback_submissions
            WHERE status = 'open'
            ORDER BY created_at ASC
            LIMIT 50
        """)
        rows = cur.fetchall()
        fb_cols = ["id", "username", "category", "title", "created_at"]
        feedback = [dict(zip(fb_cols, r)) for r in rows]
        for f in feedback:
            if f["created_at"]:
                f["created_at"] = f["created_at"].isoformat()

        return {
            "verifications": verifications,
            "disputes": disputes,
            "feedback": feedback,
            "totals": {
                "verifications": len(verifications),
                "disputes": len(disputes),
                "feedback": len(feedback),
                "total": len(verifications) + len(disputes) + len(feedback),
            },
        }, None
    except Exception as e:
        logger.error(f"get_mod_queue error: {e}", exc_info=True)
        return None, str(e)
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Community health dashboard
# ---------------------------------------------------------------------------

def get_community_health(period_days: int = 30):
    """
    Time-windowed platform health metrics for the community dashboard.
    Returns (health_dict, error).
    """
    if period_days not in (7, 30, 90):
        period_days = 30
    conn = _get_db()
    if not conn:
        return None, "Database connection failed"
    try:
        cur = conn.cursor()
        interval = f"{period_days} days"

        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE date_created >= NOW() - %s::INTERVAL) AS new_loans,
                COUNT(*) FILTER (WHERE status = 'repaid'
                    AND last_updated >= NOW() - %s::INTERVAL)                AS repaid_loans,
                COUNT(*) FILTER (WHERE status IN ('confirmed','partially_repaid')) AS active_loans,
                COUNT(*) FILTER (WHERE status = 'disputed')                  AS disputes,
                COUNT(*) FILTER (WHERE status = 'unpaid'
                    AND last_updated >= NOW() - %s::INTERVAL)                AS new_unpaid
            FROM loans
        """, (interval, interval, interval))
        loan_row = cur.fetchone()

        cur.execute("""
            SELECT COUNT(*) FROM verification_applications
            WHERE submitted_at >= NOW() - %s::INTERVAL
        """, (interval,))
        verif_requests = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*) FROM verification_applications
            WHERE status = 'approved' AND reviewed_at >= NOW() - %s::INTERVAL
        """, (interval,))
        verif_approvals = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(DISTINCT username) FROM user_roles
            WHERE last_login >= NOW() - %s::INTERVAL
        """, (interval,))
        active_users = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*) FROM feedback_submissions
            WHERE created_at >= NOW() - %s::INTERVAL
        """, (interval,))
        feedback_count = cur.fetchone()[0]

        return {
            "period_days": period_days,
            "loans": {
                "new":        loan_row[0],
                "repaid":     loan_row[1],
                "active":     loan_row[2],
                "disputes":   loan_row[3],
                "new_unpaid": loan_row[4],
            },
            "verifications": {
                "requests":  verif_requests,
                "approvals": verif_approvals,
            },
            "users": {
                "active": active_users,
            },
            "feedback": {
                "submitted": feedback_count,
            },
        }, None
    except Exception as e:
        logger.error(f"get_community_health error: {e}", exc_info=True)
        return None, str(e)
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Lender management
# ---------------------------------------------------------------------------

def get_lender_management_list(q: str = None, verified_filter: str = None,
                                limit: int = 100, offset: int = 0):
    """
    Return lenders with activity data for the management dashboard.
    Returns (list, total, error).
    """
    conn = _get_db()
    if not conn:
        return [], 0, "Database connection failed"
    try:
        cur = conn.cursor()
        conditions = ["role = 'lender'"]
        params = []
        if q:
            conditions.append("(username ILIKE %s OR reddit_username ILIKE %s)")
            params.extend([f"%{q}%", f"%{q}%"])
        if verified_filter == "verified":
            conditions.append("verified_lender = TRUE")
        elif verified_filter == "unverified":
            conditions.append("verified_lender = FALSE")
        where = "WHERE " + " AND ".join(conditions)

        cur.execute(f"SELECT COUNT(*) FROM user_roles {where}", params)
        total = cur.fetchone()[0]

        cur.execute(f"""
            SELECT ur.username, ur.verified_lender, ur.verified_lender_at,
                   ur.last_login, ur.created_at, ur.reddit_username,
                   COUNT(l.loan_id) AS loan_count,
                   COUNT(l.loan_id) FILTER (WHERE l.status IN ('confirmed','partially_repaid')) AS active_loans,
                   COUNT(l.loan_id) FILTER (WHERE l.status = 'unpaid') AS unpaid_loans
            FROM user_roles ur
            LEFT JOIN loans l ON l.lender = ur.username
            {where}
            GROUP BY ur.username, ur.verified_lender, ur.verified_lender_at,
                     ur.last_login, ur.created_at, ur.reddit_username
            ORDER BY ur.last_login DESC NULLS LAST
            LIMIT %s OFFSET %s
        """, params + [limit, offset])
        rows = cur.fetchall()
        cols = ["username", "verified_lender", "verified_lender_at", "last_login",
                "created_at", "reddit_username", "loan_count", "active_loans", "unpaid_loans"]
        result = [dict(zip(cols, r)) for r in rows]
        for item in result:
            for k in ("verified_lender_at", "last_login", "created_at"):
                if item[k]:
                    item[k] = item[k].isoformat()
        return result, total, None
    except Exception as e:
        logger.error(f"get_lender_management_list error: {e}", exc_info=True)
        return [], 0, str(e)
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Borrower activity
# ---------------------------------------------------------------------------

def get_borrower_activity_list(q: str = None, has_disputes: bool = False,
                                limit: int = 100, offset: int = 0):
    """
    Return borrowers with activity summary for the borrower dashboard.
    Returns (list, total, error).
    """
    conn = _get_db()
    if not conn:
        return [], 0, "Database connection failed"
    try:
        cur = conn.cursor()
        conditions = []
        params = []
        if q:
            conditions.append("(u.username ILIKE %s)")
            params.append(f"%{q}%")
        if has_disputes:
            conditions.append("u.unpaid_loans > 0")
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        cur.execute(f"SELECT COUNT(*) FROM users u {where}", params)
        total = cur.fetchone()[0]

        cur.execute(f"""
            SELECT u.username, u.loans_as_borrower, u.amount_borrowed,
                   u.amount_repaid, u.unpaid_loans, u.unpaid_amount,
                   ur.last_login, ur.verified_lender,
                   COUNT(l.loan_id) FILTER (WHERE l.status = 'disputed') AS disputed_count
            FROM users u
            LEFT JOIN user_roles ur ON ur.username = u.username
            LEFT JOIN loans l ON l.borrower = u.username
            {where}
            GROUP BY u.username, u.loans_as_borrower, u.amount_borrowed,
                     u.amount_repaid, u.unpaid_loans, u.unpaid_amount,
                     ur.last_login, ur.verified_lender
            ORDER BY u.loans_as_borrower DESC
            LIMIT %s OFFSET %s
        """, params + [limit, offset])
        rows = cur.fetchall()
        cols = ["username", "loans_as_borrower", "amount_borrowed", "amount_repaid",
                "unpaid_loans", "unpaid_amount", "last_login", "verified_lender",
                "disputed_count"]
        result = [dict(zip(cols, r)) for r in rows]
        for item in result:
            if item["last_login"]:
                item["last_login"] = item["last_login"].isoformat()
            for k in ("amount_borrowed", "amount_repaid", "unpaid_amount"):
                if item[k] is not None:
                    item[k] = str(item[k])
        return result, total, None
    except Exception as e:
        logger.error(f"get_borrower_activity_list error: {e}", exc_info=True)
        return [], 0, str(e)
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Announcements
# ---------------------------------------------------------------------------

def create_announcement(title: str, body: str, author: str,
                         pinned: bool = False, expires_at=None):
    """Create a platform announcement. Returns (announcement_id, error)."""
    title = title.strip()[:200]
    body  = body.strip()[:2000]
    if not title:
        return None, "Title is required"
    if not body:
        return None, "Body is required"
    conn = _get_db()
    if not conn:
        return None, "Database connection failed"
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO announcements (title, body, author, pinned, expires_at)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (title, body, author, pinned, expires_at))
        aid = cur.fetchone()[0]
        conn.commit()
        return aid, None
    except Exception as e:
        logger.error(f"create_announcement error: {e}", exc_info=True)
        return None, str(e)
    finally:
        cur.close()
        conn.close()


def get_announcements(active_only: bool = True, limit: int = 20):
    """Return platform announcements. Returns (list, error)."""
    conn = _get_db()
    if not conn:
        return [], "Database connection failed"
    try:
        cur = conn.cursor()
        where = "WHERE active = TRUE AND (expires_at IS NULL OR expires_at > NOW())" \
                if active_only else ""
        cur.execute(f"""
            SELECT id, title, body, author, pinned, active, expires_at, created_at
            FROM announcements {where}
            ORDER BY pinned DESC, created_at DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        cols = ["id", "title", "body", "author", "pinned", "active", "expires_at", "created_at"]
        result = [dict(zip(cols, r)) for r in rows]
        for item in result:
            for k in ("expires_at", "created_at"):
                if item[k]:
                    item[k] = item[k].isoformat()
        return result, None
    except Exception as e:
        logger.error(f"get_announcements error: {e}", exc_info=True)
        return [], str(e)
    finally:
        cur.close()
        conn.close()


def deactivate_announcement(announcement_id: int, actor: str):
    """Deactivate (soft-delete) an announcement. Returns (success, error)."""
    conn = _get_db()
    if not conn:
        return False, "Database connection failed"
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE announcements SET active = FALSE, updated_at = NOW()
            WHERE id = %s
        """, (announcement_id,))
        if cur.rowcount == 0:
            return False, "Announcement not found"
        conn.commit()
        return True, None
    except Exception as e:
        logger.error(f"deactivate_announcement error: {e}", exc_info=True)
        return False, str(e)
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Audit investigation summary
# ---------------------------------------------------------------------------

def get_audit_investigation_summary(username: str):
    """
    Return a complete investigation bundle for a user:
    their loans (as lender and borrower), verification history,
    recent audit actions, and basic user record.
    Returns (summary_dict, error).
    """
    conn = _get_db()
    if not conn:
        return None, "Database connection failed"
    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT username, role, verified_lender, verified_lender_at,
                   last_login, created_at, reddit_username
            FROM user_roles WHERE username = %s
        """, (username,))
        row = cur.fetchone()
        user_record = None
        if row:
            cols = ["username", "role", "verified_lender", "verified_lender_at",
                    "last_login", "created_at", "reddit_username"]
            user_record = dict(zip(cols, row))
            for k in ("verified_lender_at", "last_login", "created_at"):
                if user_record[k]:
                    user_record[k] = user_record[k].isoformat()

        cur.execute("""
            SELECT loan_id, borrower, amount, currency, status, date_created
            FROM loans WHERE lender = %s
            ORDER BY date_created DESC LIMIT 20
        """, (username,))
        lender_loans = [dict(zip(
            ["loan_id", "borrower", "amount", "currency", "status", "date_created"], r
        )) for r in cur.fetchall()]
        for l in lender_loans:
            l["amount"] = str(l["amount"])
            if l["date_created"]: l["date_created"] = l["date_created"].isoformat()

        cur.execute("""
            SELECT loan_id, lender, amount, currency, status, date_created
            FROM loans WHERE borrower = %s
            ORDER BY date_created DESC LIMIT 20
        """, (username,))
        borrower_loans = [dict(zip(
            ["loan_id", "lender", "amount", "currency", "status", "date_created"], r
        )) for r in cur.fetchall()]
        for l in borrower_loans:
            l["amount"] = str(l["amount"])
            if l["date_created"]: l["date_created"] = l["date_created"].isoformat()

        cur.execute("""
            SELECT id, status, public_note, review_note, reviewer,
                   submitted_at, reviewed_at
            FROM verification_applications WHERE username = %s
            ORDER BY submitted_at DESC
        """, (username,))
        verif_cols = ["id", "status", "public_note", "review_note", "reviewer",
                      "submitted_at", "reviewed_at"]
        verifications = [dict(zip(verif_cols, r)) for r in cur.fetchall()]
        for v in verifications:
            for k in ("submitted_at", "reviewed_at"):
                if v[k]: v[k] = v[k].isoformat()

        cur.execute("""
            SELECT action_type, actor_username, target_id, created_at
            FROM audit_logs
            WHERE actor_username = %s OR target_id = %s
            ORDER BY created_at DESC LIMIT 30
        """, (username, username))
        audit_cols = ["action_type", "actor", "target_id", "created_at"]
        audit_actions = [dict(zip(audit_cols, r)) for r in cur.fetchall()]
        for a in audit_actions:
            if a["created_at"]: a["created_at"] = a["created_at"].isoformat()

        return {
            "username": username,
            "user_record": user_record,
            "lender_loans": lender_loans,
            "borrower_loans": borrower_loans,
            "verifications": verifications,
            "audit_actions": audit_actions,
        }, None
    except Exception as e:
        logger.error(f"get_audit_investigation_summary error: {e}", exc_info=True)
        return None, str(e)
    finally:
        cur.close()
        conn.close()
