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
        log_event(
            "loan_created",
            actor=lender,
            actor_role="lender",
            target_user=borrower,
            loan_id=loan_id,
            source="service",
            details={"amount": str(amount), "currency": currency, "thread_url": thread_url},
        )
        return loan_id, None

    except Exception as e:
        conn.rollback()
        logger.error(f"create_loan error: {e}", exc_info=True)
        return None, "Database error while creating loan."
    finally:
        cur.close()
        conn.close()


def mark_repaid(loan_id: str, amount_paid: Decimal, currency: str, actor: str, actor_role: str = "lender"):
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

        # Role check
        if actor_role == "lender" and actor != lender:
            logger.warning(f"Payment auth mismatch for loan {loan_id}: actor={actor}, lender={lender}")
            return None, f"Loan ID {loan_id} exists, but it is recorded under lender u/{lender}. Only that lender can use $paid_with_id for this loan."
        if actor_role == "borrower" and actor != borrower:
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

        if amount_paid > remaining:
            return None, f"Payment amount {amount_paid:.2f} {currency} exceeds the remaining balance of {remaining:.2f} {currency}."

        new_repaid = already_repaid + amount_paid
        new_status = "repaid" if new_repaid >= loan_amount else "partially_repaid"

        cur.execute('''
            UPDATE loans SET amount_repaid = %s, status = %s, last_updated = %s WHERE id = %s
        ''', (new_repaid, new_status, datetime.now(), db_id))

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
        log_event(
            "payment_recorded",
            actor=actor,
            actor_role=actor_role,
            target_user=borrower,
            loan_id=public_id or db_id,
            source="service",
            details={
                "amount_paid": str(amount_paid),
                "currency": currency,
                "new_status": new_status,
                "remaining": str(max(loan_amount - new_repaid, Decimal("0.00"))),
            },
        )

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
                WHERE (id::text = %s OR loan_id = %s) AND lender = %s
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
                WHERE id::text = %s AND lender = %s
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
        log_event(
            "loan_marked_unpaid",
            actor=lender,
            actor_role="lender",
            target_user=borrower,
            loan_id=loan_id,
            source="service",
            details={"remaining_unpaid": str(remaining_unpaid), "currency": loan_currency},
        )

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
                WHERE (id::text = %s OR loan_id = %s) AND lender = %s
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
                WHERE id::text = %s AND lender = %s
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
        log_event(
            "loan_refunded",
            actor=lender,
            actor_role="lender",
            target_user=borrower,
            loan_id=loan_id,
            source="service",
            details={"amount": str(amount), "currency": currency},
        )

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
            where = "WHERE borrower = %s"
            params = (username, limit)
        elif role == "lender":
            where = "WHERE lender = %s"
            params = (username, limit)
        else:  # both
            where = "WHERE borrower = %s OR lender = %s"
            params = (username, username, limit)

        schema_mode = "dashboard"
        try:
            cur.execute(f'''
                SELECT id, loan_id, lender, borrower, amount, amount_repaid,
                       currency, status, date_created, original_thread, repay_date, notes, repay_amount,
                       payment_method, borrower_acknowledged_at, borrower_acknowledged_note,
                       interest_amount, interest_rate
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
                interest_amount, interest_rate = None, None
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


def set_user_role(username: str, role: str):
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
        cur.execute("""
            INSERT INTO user_roles (username, role)
            VALUES (%s, %s)
            ON CONFLICT (username) DO UPDATE SET role = %s
        """, (username.lower(), role, role))
        conn.commit()
        logger.info(f"Role set: {username} -> {role}")
        log_event(
            "role_changed",
            actor=None,
            actor_role=None,
            target_user=username,
            source="service",
            details={"role": role},
        )
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
            SELECT id, username, requested_role, status, public_note, private_note,
                   reviewer, review_note, submitted_at, reviewed_at
            FROM verification_applications
            {where}
            ORDER BY
              CASE WHEN status = 'pending' THEN 0 WHEN status = 'approved' THEN 1 ELSE 2 END,
              submitted_at DESC
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
        } for r in rows], None
    except Exception as e:
        logger.error(f"list_verification_applications error: {e}", exc_info=True)
        return None, "Database error fetching verification applications."
    finally:
        cur.close()
        conn.close()


def decide_verification_application(application_id: int, decision: str, reviewer: str,
                                    review_note: str = ""):
    """Approve or deny a verification application. Approval grants dashboard lender role."""
    decision = (decision or "").strip().lower()
    reviewer = (reviewer or "").strip().lower()
    if decision not in ("approved", "denied"):
        return None, "Decision must be approved or denied."
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
        if old_status != "pending":
            return None, f"Application is already {old_status}."

        cur.execute("""
            UPDATE verification_applications
            SET status = %s, reviewer = %s, review_note = %s, reviewed_at = NOW()
            WHERE id = %s
        """, (decision, reviewer, review_note, app_id))
        conn.commit()

        if decision == "approved" and requested_role == "lender":
            role_ok, role_error = set_user_role(username, "lender")
            if role_error:
                return None, role_error
            enqueue_reddit_action(
                "flair_sync",
                target_user=username,
                subreddit=os.getenv("PRIMARY_SUBREDDIT") or (os.getenv("SUBREDDITS", "").split(",")[0].strip() or None),
                payload={"flair_text": "Verified Lender", "requested_role": requested_role},
                reason="Verification approved; Reddit flair sync pending test/live integration.",
                created_by=reviewer,
            )

        log_event(
            "verification_decided",
            actor=reviewer,
            actor_role="mod",
            target_user=username,
            source="dashboard",
            details={"decision": decision, "requested_role": requested_role},
        )
        return {"ok": True, "id": app_id, "username": username, "status": decision}, None
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
        log_event(
            "loan_disputed",
            actor=borrower,
            actor_role="borrower",
            target_user=lender,
            loan_id=loan_id,
            source="service",
            details={"amount": str(amount), "currency": currency},
        )
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
                "detail": f"repaid {r[5]} > repay_amount {r[3]} {r[6]}"})

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
            VALUES (lower(%s), %s, NOW() + INTERVAL '%s days')
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
