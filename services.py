"""
LoanCentral Service Layer
-------------------------
All core business logic lives here.
Bot commands call these functions.
Future API/dashboard will call the same functions.
"""

import time
import logging
from datetime import datetime
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


# ---------------------------------------------------------------------------
# Loan Services
# ---------------------------------------------------------------------------

def log_action(actor: str, action: str, target: str = None, details: str = None):
    """Write a non-critical audit log entry. Never raises."""
    conn = _get_db()
    if not conn:
        return
    cur = None
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO audit_log (actor, action, target, details) VALUES (%s, %s, %s, %s)",
            (actor, action, target, details),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        if cur:
            try: cur.close()
            except Exception: pass
        try: conn.close()
        except Exception: pass


def create_loan(lender: str, borrower: str, amount: Decimal, currency: str, thread_url: str, due_date=None):
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

        cur.execute('''
            INSERT INTO loans
            (loan_id, lender, borrower, amount, currency, date_created, original_thread, status, due_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (loan_id, lender, borrower, amount, currency, datetime.now(), thread_url, 'confirmed', due_date))

        db_id = cur.fetchone()[0]

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
        log_action(lender, "loan_created", loan_id, f"{amount} {currency} -> u/{borrower}")
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

        cur.execute('''
            SELECT id, loan_id, lender, borrower, amount, amount_repaid, currency, status
            FROM loans
            WHERE id::text = %s OR loan_id = %s
            ORDER BY id DESC LIMIT 1
        ''', (loan_id, loan_id))

        result = cur.fetchone()
        if not result:
            logger.warning(f"No loan found for ID {loan_id} by {actor}")
            return None, f"Could not find a loan with ID {loan_id}. Please check the loan ID from the confirmation message."

        db_id, public_id, lender, borrower, loan_amount, already_repaid, loan_currency, status = result

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

        loan_amount = Decimal(loan_amount)
        already_repaid = Decimal(already_repaid)
        remaining = loan_amount - already_repaid

        if amount_paid > remaining:
            return None, f"Payment amount {amount_paid:.2f} {currency} exceeds the remaining balance of {remaining:.2f} {currency}."

        new_repaid = already_repaid + amount_paid
        new_status = "repaid" if new_repaid >= loan_amount else "partially_repaid"

        date_repaid_val = datetime.now() if new_status == "repaid" else None

        cur.execute('''
            UPDATE loans SET amount_repaid = %s, status = %s, last_updated = %s,
            date_repaid = COALESCE(date_repaid, %s) WHERE id = %s
        ''', (new_repaid, new_status, datetime.now(), date_repaid_val, db_id))

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
        log_action(lender, "payment_recorded", str(loan_id),
                   f"{amount_paid} {currency} from u/{borrower} ({new_status})")

        return {
            "db_id": db_id,
            "lender": lender,
            "borrower": borrower,
            "loan_amount": loan_amount,
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

        cur.execute('''
            SELECT id, amount, currency, amount_repaid, original_thread, status, borrower
            FROM loans
            WHERE (id::text = %s OR loan_id = %s) AND lender = %s
            ORDER BY id DESC LIMIT 1
        ''', (loan_id, loan_id, lender))

        result = cur.fetchone()
        if not result:
            logger.warning(f"No matching loan found for unpaid: ID {loan_id} by {lender}")
            return None, f"Could not find a loan with ID {loan_id} where you are the lender."

        db_id, loan_amount, loan_currency, amount_repaid, thread_url, status, borrower = result

        if status == "unpaid":
            return None, "This loan is already marked unpaid."
        if status == "repaid":
            return None, "This loan has already been fully repaid."
        if status == "refunded":
            return None, "This loan has been refunded."

        cur.execute('''
            UPDATE loans SET status = 'unpaid', last_updated = %s WHERE id = %s
        ''', (datetime.now(), db_id))

        remaining_unpaid = Decimal(loan_amount) - Decimal(amount_repaid)
        cur.execute('''
            UPDATE users SET
                unpaid_loans = unpaid_loans + 1,
                unpaid_amount = unpaid_amount + %s,
                last_updated = %s
            WHERE username = %s
        ''', (remaining_unpaid, datetime.now(), borrower))

        conn.commit()
        logger.info(f"Loan {db_id} marked unpaid by {lender}")
        log_action(lender, "loan_unpaid", str(db_id), f"u/{borrower} {loan_amount} {loan_currency}")

        return {
            "db_id": db_id,
            "lender": lender,
            "borrower": borrower,
            "loan_amount": Decimal(loan_amount),
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

        cur.execute('''
            SELECT id, borrower, amount, currency, status
            FROM loans
            WHERE (id::text = %s OR loan_id = %s) AND lender = %s
            ORDER BY id DESC LIMIT 1
        ''', (loan_id, loan_id, lender))

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
        log_action(lender, "loan_refunded", str(db_id), f"u/{borrower} {amount} {currency}")

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

        cur.execute('''
            SELECT COUNT(*), COALESCE(SUM(amount - amount_repaid), 0)
            FROM loans WHERE borrower = %s AND status IN ('confirmed', 'partially_repaid')
        ''', (username.lower(),))

        active = cur.fetchone()

        cur.execute('''
            SELECT COUNT(*), COALESCE(SUM(amount - amount_repaid), 0)
            FROM loans WHERE lender = %s AND status IN ('confirmed', 'partially_repaid')
        ''', (username.lower(),))

        active_lent = cur.fetchone()

        cur.execute('''
            SELECT COUNT(*) FROM loans WHERE lender = %s AND status = 'unpaid'
        ''', (username.lower(),))

        lender_unpaid_row = cur.fetchone()

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
                "active_loans_given": 0,
                "active_amount_given": Decimal("0"),
                "borrowers_unpaid": 0,
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
            "active_loans_given": active_lent[0] if active_lent else 0,
            "active_amount_given": Decimal(active_lent[1]) if active_lent else Decimal("0"),
            "borrowers_unpaid": lender_unpaid_row[0] if lender_unpaid_row else 0,
        }, None

    except Exception as e:
        logger.error(f"get_user_profile error: {e}", exc_info=True)
        return None, "Database error fetching user profile."
    finally:
        cur.close()
        conn.close()


def calculate_health_score(profile: dict) -> tuple:
    """
    Calculate a borrower health score (0-100) from a user profile dict.
    Returns (score: int, label: str)
    """
    total = profile.get("loans_as_borrower") or 0
    if not total:
        return 100, "No history"
    unpaid = profile.get("unpaid_loans") or 0
    paid = total - unpaid
    loan_ratio = paid / total
    borrowed = float(profile.get("amount_borrowed") or 0)
    repaid = float(profile.get("amount_repaid") or 0)
    pay_ratio = min(repaid / borrowed, 1.0) if borrowed > 0 else 1.0
    score = round((loan_ratio * 0.7 + pay_ratio * 0.3) * 100)
    if score >= 90:
        label = "Excellent"
    elif score >= 70:
        label = "Good"
    elif score >= 50:
        label = "Fair"
    elif score >= 25:
        label = "Poor"
    else:
        label = "Very Poor"
    return score, label


def get_loan_history(username: str, role: str = "both", limit: int = 50, offset: int = 0,
                     search: str = None):
    """
    Fetch recent loans for a user.
    role: "borrower", "lender", or "both"
    search: optional filter by counterparty username or loan_id
    Returns (list_of_loan_dicts, error_message)
    """
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."

    try:
        cur = conn.cursor()
        username = username.lower()

        if role == "borrower":
            if search:
                where  = "WHERE borrower = %s AND (lender ILIKE %s OR loan_id ILIKE %s)"
                params = (username, f"%{search}%", f"%{search}%", limit, offset)
            else:
                where  = "WHERE borrower = %s"
                params = (username, limit, offset)
        elif role == "lender":
            if search:
                where  = "WHERE lender = %s AND (borrower ILIKE %s OR loan_id ILIKE %s)"
                params = (username, f"%{search}%", f"%{search}%", limit, offset)
            else:
                where  = "WHERE lender = %s"
                params = (username, limit, offset)
        else:  # both
            if search:
                where  = ("WHERE (borrower = %s OR lender = %s) "
                          "AND (lender ILIKE %s OR borrower ILIKE %s OR loan_id ILIKE %s)")
                params = (username, username, f"%{search}%", f"%{search}%", f"%{search}%", limit, offset)
            else:
                where  = "WHERE borrower = %s OR lender = %s"
                params = (username, username, limit, offset)

        cur.execute(f'''
            SELECT id, loan_id, lender, borrower, amount, amount_repaid,
                   currency, status, date_created, original_thread, date_repaid, due_date
            FROM loans {where}
            ORDER BY date_created DESC
            LIMIT %s OFFSET %s
        ''', params)

        rows = cur.fetchall()
        loans = [
            {
                "db_id": r[0],
                "loan_id": r[1],
                "lender": r[2],
                "borrower": r[3],
                "amount": Decimal(r[4]),
                "amount_repaid": Decimal(r[5]),
                "currency": r[6],
                "status": r[7],
                "date_created": r[8],
                "original_thread": r[9],
                "date_repaid": r[10],
                "due_date": r[11],
                "repaid_pct": round(float(r[5]) / float(r[4]) * 100, 1) if float(r[4]) > 0 else 0,
            }
            for r in rows
        ]
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
        cur.execute('''
            SELECT id, loan_id, lender, borrower, amount, amount_repaid,
                   currency, status, date_created, original_thread
            FROM loans
            WHERE borrower = %s AND status IN ('confirmed', 'partially_repaid')
            ORDER BY date_created ASC
        ''', (username.lower(),))

        rows = cur.fetchall()
        loans = [
            {
                "db_id": r[0],
                "loan_id": r[1],
                "lender": r[2],
                "borrower": r[3],
                "amount": Decimal(r[4]),
                "amount_repaid": Decimal(r[5]),
                "remaining": Decimal(r[4]) - Decimal(r[5]),
                "currency": r[6],
                "status": r[7],
                "date_created": r[8],
                "original_thread": r[9],
            }
            for r in rows
        ]
        return loans, None

    except Exception as e:
        logger.error(f"get_active_loans error: {e}", exc_info=True)
        return None, "Database error fetching active loans."
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Role / Auth Services
# ---------------------------------------------------------------------------

def get_user_role(username: str):
    """
    Get dashboard role for a user.
    Returns ('borrower'|'lender'|'mod', error_message).
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


def set_user_role(username: str, role: str, actor: str = "system"):
    """
    Set or update a user's dashboard role.
    role must be 'mod', 'lender', or 'borrower'.
    Returns (True, None) on success or (None, error_message).
    """
    if role not in ("mod", "lender", "borrower"):
        return None, "Role must be 'mod', 'lender', or 'borrower'."
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
        log_action(actor, "role_changed", username.lower(), f"-> {role}")
        return True, None
    except Exception as e:
        conn.rollback()
        logger.error(f"set_user_role error: {e}", exc_info=True)
        return None, str(e)
    finally:
        cur.close()
        conn.close()


def set_password(username: str, password: str):
    """Set or replace a user's dashboard password hash."""
    from werkzeug.security import generate_password_hash
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()
        pw_hash = generate_password_hash(password)
        cur.execute("""
            INSERT INTO user_roles (username, role, password_hash)
            VALUES (%s, 'borrower', %s)
            ON CONFLICT (username) DO UPDATE SET password_hash = %s
        """, (username.lower(), pw_hash, pw_hash))
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        logger.error(f"set_password error: {e}", exc_info=True)
        return None, str(e)
    finally:
        cur.close()
        conn.close()


def verify_password(username: str, password: str):
    """Verify username + password. Returns (role, error)."""
    from werkzeug.security import check_password_hash
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT role, password_hash FROM user_roles WHERE username = %s",
            (username.lower(),)
        )
        row = cur.fetchone()
        if not row or not row[1]:
            return None, "Invalid username or password."
        role, pw_hash = row
        if not check_password_hash(pw_hash, password):
            return None, "Invalid username or password."
        return role, None
    except Exception as e:
        logger.error(f"verify_password error: {e}", exc_info=True)
        return None, "Database error."
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


def set_phone_number(username: str, phone: str):
    """Store a US/Canada phone number for SMS reminders."""
    import re
    phone = re.sub(r"[^\d+]", "", phone.strip())
    if not phone.startswith("+"):
        phone = "+1" + phone  # US/Canada +1
    if not phone.startswith("+1") or len(phone) != 12:
        return None, "Please enter a valid US or Canadian phone number."
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO user_roles (username, role, phone_number)
            VALUES (%s, 'borrower', %s)
            ON CONFLICT (username) DO UPDATE SET phone_number = %s
        """, (username.lower(), phone, phone))
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        logger.error(f"set_phone_number error: {e}", exc_info=True)
        return None, str(e)
    finally:
        cur.close()
        conn.close()


def get_loans_for_reminder():
    """
    Return loans that need an SMS reminder:
    - Active/partial loans older than 7 days, not reminded in last 7 days
    - Unpaid loans not reminded in last 3 days
    Each row includes borrower phone number (skips users with no phone).
    """
    conn = _get_db()
    if not conn:
        return [], "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                l.id, l.loan_id, l.lender, l.borrower,
                l.amount, l.currency, l.status, l.date_created,
                ur.phone_number
            FROM loans l
            JOIN user_roles ur ON ur.username = l.borrower
            WHERE ur.phone_number IS NOT NULL
              AND (
                (l.status IN ('confirmed', 'partially_repaid')
                 AND l.date_created <= NOW() - INTERVAL '7 days'
                 AND (l.last_reminder_sent IS NULL
                      OR l.last_reminder_sent <= NOW() - INTERVAL '7 days'))
                OR
                (l.status = 'unpaid'
                 AND (l.last_reminder_sent IS NULL
                      OR l.last_reminder_sent <= NOW() - INTERVAL '3 days'))
              )
            ORDER BY l.status, l.date_created
        """)
        rows = cur.fetchall()
        return [
            {
                "db_id": r[0], "loan_id": r[1], "lender": r[2],
                "borrower": r[3], "amount": float(r[4]), "currency": r[5],
                "status": r[6], "date_created": r[7], "phone": r[8],
                "reminder_type": "unpaid" if r[6] == "unpaid" else "periodic",
            }
            for r in rows
        ], None
    except Exception as e:
        logger.error(f"get_loans_for_reminder error: {e}", exc_info=True)
        return [], str(e)
    finally:
        cur.close()
        conn.close()


def mark_reminder_sent(db_id: int):
    """Update last_reminder_sent timestamp for a loan."""
    conn = _get_db()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE loans SET last_reminder_sent = NOW() WHERE id = %s",
            (db_id,)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"mark_reminder_sent error: {e}", exc_info=True)
        conn.rollback()
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
        cur.execute("""
            SELECT
                COUNT(*)                                                    AS total,
                COUNT(*) FILTER (WHERE status IN ('confirmed','partially_repaid')) AS active,
                COUNT(*) FILTER (WHERE status = 'unpaid')                  AS unpaid,
                COUNT(*) FILTER (WHERE status = 'repaid')                  AS repaid,
                COALESCE(SUM(amount), 0)                                   AS total_lent,
                COALESCE(SUM(amount_repaid), 0)                            AS total_recovered,
                COALESCE(SUM(amount) FILTER (WHERE status IN ('confirmed','partially_repaid','unpaid')), 0) AS outstanding
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


def get_borrower_stats(borrower: str):
    """
    Get borrowing stats for a specific borrower.
    Returns (stats_dict, error_message).
    """
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                COUNT(*)                                                       AS total,
                COUNT(*) FILTER (WHERE status IN ('confirmed','partially_repaid')) AS active,
                COUNT(*) FILTER (WHERE status = 'unpaid')                     AS unpaid,
                COUNT(*) FILTER (WHERE status = 'repaid')                     AS repaid,
                COALESCE(SUM(amount), 0)                                      AS total_borrowed,
                COALESCE(SUM(amount_repaid), 0)                               AS total_repaid,
                COALESCE(SUM(amount) FILTER (
                    WHERE status IN ('confirmed','partially_repaid','unpaid')), 0) AS outstanding,
                COUNT(*) FILTER (WHERE due_date IS NOT NULL
                                  AND due_date < NOW()
                                  AND status NOT IN ('repaid','refunded','unpaid')) AS overdue
            FROM loans WHERE borrower = %s
        """, (borrower.lower(),))
        row = cur.fetchone()
        return {
            "total_loans":    row[0],
            "active_loans":   row[1],
            "unpaid_loans":   row[2],
            "repaid_loans":   row[3],
            "total_borrowed": row[4],
            "total_repaid":   row[5],
            "outstanding":    row[6],
            "overdue_loans":  row[7],
        }, None
    except Exception as e:
        logger.error(f"get_borrower_stats error: {e}", exc_info=True)
        return None, str(e)
    finally:
        cur.close()
        conn.close()


def send_due_reminders():
    """
    Query loans due within 3 days where borrower has a phone number,
    send SMS via Twilio, and mark them as reminded.
    Returns (count_sent, error_message).
    """
    from notifications import send_sms
    conn = _get_db()
    if not conn:
        return 0, "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT l.id, l.loan_id, l.lender, l.borrower,
                   l.amount, l.currency, l.due_date,
                   ur.phone_number
            FROM loans l
            JOIN user_roles ur ON ur.username = l.borrower
            WHERE l.status IN ('confirmed', 'partially_repaid')
              AND l.due_date IS NOT NULL
              AND l.due_date BETWEEN NOW() AND NOW() + INTERVAL '3 days'
              AND ur.phone_number IS NOT NULL
              AND (l.last_reminder_sent IS NULL
                   OR l.last_reminder_sent < NOW() - INTERVAL '24 hours')
        """)
        rows = cur.fetchall()
    except Exception as e:
        logger.error(f"send_due_reminders query error: {e}", exc_info=True)
        return 0, str(e)
    finally:
        try: cur.close()
        except Exception: pass
        try: conn.close()
        except Exception: pass

    count = 0
    for r in rows:
        db_id, loan_id, lender, borrower, amount, currency, due_date, phone = r
        try:
            days_left = max((due_date.date() - datetime.now().date()).days, 0)
            msg = (
                f"LoanCentral: Your loan of {float(amount):.2f} {currency} "
                f"from u/{lender} (#{loan_id}) is due in {days_left} day(s). "
                f"Please arrange repayment soon."
            )
            send_sms(phone, msg)
            mark_reminder_sent(db_id)
            count += 1
            logger.info(f"Due-date SMS sent: loan #{loan_id} -> u/{borrower}")
        except Exception as e:
            logger.error(f"SMS due-reminder failed for u/{borrower} loan {loan_id}: {e}")
    return count, None


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def get_audit_log(limit: int = 100, offset: int = 0):
    conn = _get_db()
    if not conn:
        return [], "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT actor, action, target, details, created_at
            FROM audit_log ORDER BY created_at DESC LIMIT %s OFFSET %s
        """, (limit, offset))
        return [
            {"actor": r[0], "action": r[1], "target": r[2],
             "details": r[3], "created_at": r[4]}
            for r in cur.fetchall()
        ], None
    except Exception as e:
        logger.error(f"get_audit_log error: {e}", exc_info=True)
        return [], str(e)
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Loan applications
# ---------------------------------------------------------------------------

def submit_loan_application(borrower: str, amount: Decimal, currency: str,
                             reason: str = None, repayment_plan: str = None):
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()
        # Limit: max 3 open applications per borrower
        cur.execute(
            "SELECT COUNT(*) FROM loan_applications WHERE borrower = %s AND status = 'open'",
            (borrower.lower(),)
        )
        open_count = cur.fetchone()[0]
        if open_count >= 3:
            return None, "You already have 3 open loan requests. Cancel one before submitting a new one."
        cur.execute("""
            INSERT INTO loan_applications (borrower, amount, currency, reason, repayment_plan)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
        """, (borrower.lower(), amount, currency.upper(), reason, repayment_plan))
        app_id = cur.fetchone()[0]
        conn.commit()
        log_action(borrower, "app_submitted", str(app_id), f"{amount} {currency}")
        return app_id, None
    except Exception as e:
        conn.rollback()
        logger.error(f"submit_loan_application error: {e}", exc_info=True)
        return None, str(e)
    finally:
        cur.close()
        conn.close()


def get_loan_applications(status: str = None, borrower: str = None,
                           lender: str = None, limit: int = 50, offset: int = 0):
    conn = _get_db()
    if not conn:
        return [], "Database connection failed."
    try:
        cur = conn.cursor()
        conditions, params = [], []
        if status:
            conditions.append("status = %s"); params.append(status)
        if borrower:
            conditions.append("borrower = %s"); params.append(borrower.lower())
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params += [limit, offset]
        cur.execute(f"""
            SELECT id, borrower, amount, currency, reason, repayment_plan,
                   status, lender, created_at, updated_at
            FROM loan_applications {where}
            ORDER BY created_at DESC LIMIT %s OFFSET %s
        """, params)
        return [
            {"id": r[0], "borrower": r[1], "amount": r[2], "currency": r[3],
             "reason": r[4], "repayment_plan": r[5], "status": r[6],
             "lender": r[7], "created_at": r[8], "updated_at": r[9]}
            for r in cur.fetchall()
        ], None
    except Exception as e:
        logger.error(f"get_loan_applications error: {e}", exc_info=True)
        return [], str(e)
    finally:
        cur.close()
        conn.close()


def update_loan_application(app_id: int, status: str, actor: str, lender: str = None):
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()
        if lender:
            cur.execute("""
                UPDATE loan_applications SET status = %s, lender = %s, updated_at = NOW()
                WHERE id = %s RETURNING id
            """, (status, lender.lower(), app_id))
        else:
            cur.execute("""
                UPDATE loan_applications SET status = %s, updated_at = NOW()
                WHERE id = %s RETURNING id
            """, (status, app_id))
        if not cur.fetchone():
            return None, "Application not found."
        conn.commit()
        log_action(actor, f"app_{status}", str(app_id))
        return True, None
    except Exception as e:
        conn.rollback()
        logger.error(f"update_loan_application error: {e}", exc_info=True)
        return None, str(e)
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Lender availability
# ---------------------------------------------------------------------------

def set_lender_availability(username: str, available: bool):
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO user_roles (username, role, available)
            VALUES (%s, 'lender', %s)
            ON CONFLICT (username) DO UPDATE SET available = %s
        """, (username.lower(), available, available))
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        logger.error(f"set_lender_availability error: {e}", exc_info=True)
        return None, str(e)
    finally:
        cur.close()
        conn.close()


def get_available_lenders():
    conn = _get_db()
    if not conn:
        return [], "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT ur.username, COALESCE(u.loans_as_lender, 0), COALESCE(u.amount_lent, 0)
            FROM user_roles ur
            LEFT JOIN users u ON u.username = ur.username
            WHERE ur.role IN ('lender', 'mod') AND ur.available = true
            ORDER BY COALESCE(u.amount_lent, 0) DESC
        """)
        return [
            {"username": r[0], "loans_as_lender": r[1], "amount_lent": float(r[2])}
            for r in cur.fetchall()
        ], None
    except Exception as e:
        logger.error(f"get_available_lenders error: {e}", exc_info=True)
        return [], str(e)
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Bulk mod actions
# ---------------------------------------------------------------------------

def bulk_loan_action(loan_ids: list, action: str, actor: str):
    """
    Mod-only bulk action on a list of loan IDs.
    action: 'unpaid' or 'refunded'
    Returns {'success': int, 'failed': int, 'errors': list}
    """
    results = {"success": 0, "failed": 0, "errors": []}
    if not loan_ids or action not in ("unpaid", "refunded"):
        results["errors"].append("Invalid parameters.")
        return results

    for loan_id in loan_ids[:50]:  # hard cap — no runaway bulk ops
        try:
            if action == "unpaid":
                # Look up the lender so mark_unpaid can verify it
                conn = _get_db()
                if not conn:
                    results["failed"] += 1
                    continue
                try:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT lender FROM loans WHERE id::text = %s OR loan_id = %s LIMIT 1",
                        (str(loan_id), str(loan_id)),
                    )
                    row = cur.fetchone()
                finally:
                    try: cur.close()
                    except Exception: pass
                    try: conn.close()
                    except Exception: pass
                if not row:
                    results["failed"] += 1
                    results["errors"].append(f"Loan {loan_id}: not found")
                    continue
                _, error = mark_unpaid(str(loan_id), row[0])
            else:
                _, error = mark_refunded_by_id(str(loan_id), _get_lender_for_id(str(loan_id)))

            if error:
                results["failed"] += 1
                results["errors"].append(f"Loan {loan_id}: {error}")
            else:
                results["success"] += 1
                log_action(actor, f"bulk_{action}", str(loan_id))
        except Exception as e:
            results["failed"] += 1
            results["errors"].append(f"Loan {loan_id}: {e}")

    return results


def _get_lender_for_id(loan_id: str):
    """Return lender username for a loan id, or empty string."""
    conn = _get_db()
    if not conn:
        return ""
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT lender FROM loans WHERE id::text = %s OR loan_id = %s LIMIT 1",
            (loan_id, loan_id),
        )
        row = cur.fetchone()
        return row[0] if row else ""
    except Exception:
        return ""
    finally:
        try: cur.close()
        except Exception: pass
        try: conn.close()
        except Exception: pass


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

def get_leaderboard():
    """Top 10 lenders by volume + top 10 borrowers by repayment rate."""
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT username, loans_as_lender, amount_lent
            FROM users WHERE loans_as_lender > 0
            ORDER BY amount_lent DESC LIMIT 10
        """)
        lenders = [
            {"username": r[0], "loans": r[1], "amount_lent": float(r[2])}
            for r in cur.fetchall()
        ]

        cur.execute("""
            SELECT username, loans_as_borrower, amount_borrowed, amount_repaid
            FROM users WHERE loans_as_borrower >= 2 AND amount_borrowed > 0
            ORDER BY (amount_repaid / amount_borrowed) DESC LIMIT 10
        """)
        borrowers = [
            {
                "username": r[0],
                "loans": r[1],
                "amount_borrowed": float(r[2]),
                "amount_repaid": float(r[3]),
                "repay_rate": round(float(r[3]) / float(r[2]) * 100, 1) if float(r[2]) > 0 else 0,
            }
            for r in cur.fetchall()
        ]

        return {"lenders": lenders, "borrowers": borrowers}, None
    except Exception as e:
        logger.error(f"get_leaderboard error: {e}", exc_info=True)
        return None, str(e)
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Repayment tier (derived from repayment score)
# ---------------------------------------------------------------------------

def credit_tier(score: int) -> dict:
    """Return standing label and color class for a repayment score."""
    if score >= 90:
        return {"label": "Trusted Borrower", "color": "green"}
    if score >= 70:
        return {"label": "Good Standing",    "color": "accent"}
    if score >= 50:
        return {"label": "Fair Standing",    "color": "yellow"}
    if score >= 25:
        return {"label": "At Risk",          "color": "orange"}
    return         {"label": "High Risk",    "color": "red"}


# ---------------------------------------------------------------------------
# Mod notes on loans
# ---------------------------------------------------------------------------

def add_loan_note(loan_id: str, note: str, actor: str):
    """Set or replace the mod note on a loan."""
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE loans SET notes = %s WHERE id::text = %s OR loan_id = %s RETURNING id",
            (note.strip()[:1000] if note else None, loan_id, loan_id),
        )
        if not cur.fetchone():
            return None, "Loan not found."
        conn.commit()
        log_action(actor, "loan_note_set", str(loan_id), note[:100] if note else "(cleared)")
        return True, None
    except Exception as e:
        conn.rollback()
        logger.error(f"add_loan_note error: {e}", exc_info=True)
        return None, str(e)
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Disputes
# ---------------------------------------------------------------------------

def submit_dispute(loan_id: str, borrower: str, reason: str):
    """Borrower files a dispute on a loan marked unpaid."""
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, status, borrower FROM loans WHERE id::text = %s OR loan_id = %s ORDER BY id DESC LIMIT 1",
            (loan_id, loan_id),
        )
        row = cur.fetchone()
        if not row:
            return None, "Loan not found."
        db_id, status, loan_borrower = row
        if loan_borrower != borrower.lower():
            return None, "You can only dispute your own loans."
        if status != "unpaid":
            return None, "Only loans marked 'unpaid' can be disputed."

        cur.execute(
            "SELECT id FROM disputes WHERE loan_id = %s AND status = 'open'",
            (db_id,)
        )
        if cur.fetchone():
            return None, "You already have an open dispute for this loan."

        cur.execute(
            "INSERT INTO disputes (loan_id, borrower, reason) VALUES (%s, %s, %s) RETURNING id",
            (db_id, borrower.lower(), (reason or "").strip()[:500]),
        )
        dispute_id = cur.fetchone()[0]
        conn.commit()
        log_action(borrower, "dispute_filed", str(db_id), reason[:100] if reason else None)
        return dispute_id, None
    except Exception as e:
        conn.rollback()
        logger.error(f"submit_dispute error: {e}", exc_info=True)
        return None, str(e)
    finally:
        cur.close()
        conn.close()


def get_disputes(status: str = None, limit: int = 50, offset: int = 0):
    """Get disputes for mod review."""
    conn = _get_db()
    if not conn:
        return [], "Database connection failed."
    try:
        cur = conn.cursor()
        where = "WHERE d.status = %s" if status else ""
        params = [status] if status else []
        params += [limit, offset]
        cur.execute(f"""
            SELECT d.id, d.loan_id, d.borrower, d.reason, d.status,
                   d.resolution, d.created_at, d.resolved_at, d.resolved_by,
                   l.amount, l.currency, l.lender
            FROM disputes d
            JOIN loans l ON l.id = d.loan_id
            {where}
            ORDER BY d.created_at DESC LIMIT %s OFFSET %s
        """, params)
        return [
            {
                "id": r[0], "loan_id": r[1], "borrower": r[2], "reason": r[3],
                "status": r[4], "resolution": r[5], "created_at": r[6],
                "resolved_at": r[7], "resolved_by": r[8],
                "loan_amount": float(r[9]), "loan_currency": r[10], "lender": r[11],
            }
            for r in cur.fetchall()
        ], None
    except Exception as e:
        logger.error(f"get_disputes error: {e}", exc_info=True)
        return [], str(e)
    finally:
        cur.close()
        conn.close()


def resolve_dispute(dispute_id: int, action: str, actor: str, resolution: str = None):
    """
    Resolve a dispute.
    action: 'accept' (revert loan to confirmed, clear unpaid stats) or 'dismiss'.
    """
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT d.loan_id, d.borrower, d.status, l.amount, l.currency, l.amount_repaid "
            "FROM disputes d JOIN loans l ON l.id = d.loan_id WHERE d.id = %s",
            (dispute_id,),
        )
        row = cur.fetchone()
        if not row:
            return None, "Dispute not found."
        loan_id, borrower, d_status, amount, currency, amount_repaid = row
        if d_status != "open":
            return None, "This dispute has already been resolved."

        new_status = "resolved" if action == "accept" else "dismissed"
        cur.execute("""
            UPDATE disputes SET status = %s, resolution = %s,
            resolved_at = NOW(), resolved_by = %s WHERE id = %s
        """, (new_status, (resolution or "").strip()[:500], actor.lower(), dispute_id))

        if action == "accept":
            # Revert loan to confirmed; reverse unpaid stats
            cur.execute(
                "UPDATE loans SET status = 'confirmed', last_updated = NOW() WHERE id = %s",
                (loan_id,),
            )
            remaining = Decimal(str(amount)) - Decimal(str(amount_repaid))
            cur.execute("""
                UPDATE users SET
                    unpaid_loans  = GREATEST(unpaid_loans  - 1, 0),
                    unpaid_amount = GREATEST(unpaid_amount - %s, 0),
                    last_updated  = NOW()
                WHERE username = %s
            """, (remaining, borrower))

        conn.commit()
        log_action(actor, f"dispute_{new_status}", str(dispute_id),
                   resolution[:100] if resolution else None)
        return True, None
    except Exception as e:
        conn.rollback()
        logger.error(f"resolve_dispute error: {e}", exc_info=True)
        return None, str(e)
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Due-date reminders (separate from periodic reminders)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Bot heartbeat
# ---------------------------------------------------------------------------

def update_bot_heartbeat(comment_delta: int = 0):
    """Write a heartbeat timestamp to bot_status. Silent fail."""
    conn = _get_db()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO bot_status (id, last_heartbeat, comment_count)
            VALUES (1, NOW(), %s)
            ON CONFLICT (id) DO UPDATE SET
                last_heartbeat = NOW(),
                comment_count  = bot_status.comment_count + %s
        """, (comment_delta, comment_delta))
        conn.commit()
    except Exception:
        pass
    finally:
        try: cur.close()
        except Exception: pass
        try: conn.close()
        except Exception: pass


def get_bot_status():
    """Return bot liveness info dict, or None."""
    conn = _get_db()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT last_heartbeat, comment_count, started_at FROM bot_status WHERE id = 1"
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "last_heartbeat": row[0],
            "comment_count":  row[1],
            "started_at":     row[2],
        }
    except Exception:
        return None
    finally:
        try: cur.close()
        except Exception: pass
        try: conn.close()
        except Exception: pass


# ---------------------------------------------------------------------------
# Role requests (bot-side helper)
# ---------------------------------------------------------------------------

def submit_role_request(username: str, requested_role: str, reason: str = None):
    """
    Create or update a pending role request.
    Returns (True, None) on success or (None, error_str).
    """
    if requested_role not in ("lender", "mod"):
        return None, "Invalid role. Only 'lender' requests are accepted via bot."
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO role_requests (username, requested_role, reason, status, created_at)
            VALUES (%s, %s, %s, 'pending', NOW())
            ON CONFLICT (username) DO UPDATE
                SET requested_role = %s, reason = %s, status = 'pending', created_at = NOW()
        """, (username.lower(), requested_role, reason, requested_role, reason))
        conn.commit()
        log_action(username, "role_requested", requested_role, reason[:100] if reason else None)
        return True, None
    except Exception as e:
        conn.rollback()
        logger.error(f"submit_role_request error: {e}", exc_info=True)
        return None, str(e)
    finally:
        cur.close()
        conn.close()


def get_loans_approaching_due(days_ahead: int = 3):
    """
    Return active loans with due_date within the next N days that haven't been
    reminded in the past day. Includes borrower phone number.
    """
    conn = _get_db()
    if not conn:
        return [], "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                l.id, l.loan_id, l.lender, l.borrower,
                l.amount, l.currency, l.status, l.due_date,
                ur.phone_number
            FROM loans l
            JOIN user_roles ur ON ur.username = l.borrower
            WHERE ur.phone_number IS NOT NULL
              AND l.status IN ('confirmed', 'partially_repaid')
              AND l.due_date IS NOT NULL
              AND l.due_date BETWEEN NOW() AND NOW() + INTERVAL '%s days'
              AND (l.last_reminder_sent IS NULL
                   OR l.last_reminder_sent <= NOW() - INTERVAL '1 day')
            ORDER BY l.due_date
        """, (days_ahead,))
        rows = cur.fetchall()
        return [
            {
                "db_id": r[0], "loan_id": r[1], "lender": r[2],
                "borrower": r[3], "amount": float(r[4]), "currency": r[5],
                "status": r[6], "due_date": r[7], "phone": r[8],
                "reminder_type": "due_soon",
            }
            for r in rows
        ], None
    except Exception as e:
        logger.error(f"get_loans_approaching_due error: {e}", exc_info=True)
        return [], str(e)
    finally:
        cur.close()
        conn.close()


def check_ban(username: str):
    """Check if a user is banned. Returns (is_banned, reason)."""
    conn = _get_db()
    if not conn:
        return False, None
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT reason FROM banned_users WHERE username = %s",
            (username.lower(),)
        )
        row = cur.fetchone()
        if row:
            return True, row[0] or "No reason provided."
        return False, None
    except Exception as e:
        logger.warning(f"check_ban error for {username}: {e}")
        return False, None
    finally:
        cur.close()
        conn.close()


def ban_user(username: str, reason: str, banned_by: str):
    """Ban a user. Returns (success, error)."""
    conn = _get_db()
    if not conn:
        return False, "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO banned_users (username, reason, banned_by)
            VALUES (%s, %s, %s)
            ON CONFLICT (username) DO UPDATE
                SET reason = EXCLUDED.reason,
                    banned_by = EXCLUDED.banned_by,
                    banned_at = NOW()
            """,
            (username.lower(), reason, banned_by.lower())
        )
        conn.commit()
        log_action(banned_by, "user_banned", username, reason or "no reason")
        logger.info(f"u/{username} banned by u/{banned_by}: {reason}")
        return True, None
    except Exception as e:
        logger.error(f"ban_user error: {e}", exc_info=True)
        return False, str(e)
    finally:
        cur.close()
        conn.close()


def unban_user(username: str, unbanned_by: str):
    """Unban a user. Returns (success, error)."""
    conn = _get_db()
    if not conn:
        return False, "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM banned_users WHERE username = %s RETURNING username",
            (username.lower(),)
        )
        row = cur.fetchone()
        if not row:
            return False, f"u/{username} is not banned."
        conn.commit()
        log_action(unbanned_by, "user_unbanned", username, "")
        logger.info(f"u/{username} unbanned by u/{unbanned_by}")
        return True, None
    except Exception as e:
        logger.error(f"unban_user error: {e}", exc_info=True)
        return False, str(e)
    finally:
        cur.close()
        conn.close()


def list_banned_users():
    """Return list of all banned users. Returns (list, error)."""
    conn = _get_db()
    if not conn:
        return [], "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT username, reason, banned_by, banned_at FROM banned_users ORDER BY banned_at DESC"
        )
        rows = cur.fetchall()
        return [
            {"username": r[0], "reason": r[1], "banned_by": r[2], "banned_at": r[3]}
            for r in rows
        ], None
    except Exception as e:
        logger.error(f"list_banned_users error: {e}", exc_info=True)
        return [], str(e)
    finally:
        cur.close()
        conn.close()


def add_mod_note(username: str, note: str, added_by: str):
    """Add a mod note to a user. Returns (note_id, error)."""
    conn = _get_db()
    if not conn:
        return None, "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO mod_notes (username, note, added_by) VALUES (%s, %s, %s) RETURNING id",
            (username.lower(), note.strip()[:500], added_by.lower())
        )
        note_id = cur.fetchone()[0]
        conn.commit()
        log_action(added_by, "mod_note_added", username, note[:100])
        return note_id, None
    except Exception as e:
        logger.error(f"add_mod_note error: {e}", exc_info=True)
        return None, str(e)
    finally:
        cur.close()
        conn.close()


def get_mod_notes(username: str):
    """Get all mod notes for a user. Returns (list, error)."""
    conn = _get_db()
    if not conn:
        return [], "Database connection failed."
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, note, added_by, created_at FROM mod_notes "
            "WHERE username = %s ORDER BY created_at DESC",
            (username.lower(),)
        )
        rows = cur.fetchall()
        return [
            {"id": r[0], "note": r[1], "added_by": r[2], "created_at": r[3]}
            for r in rows
        ], None
    except Exception as e:
        logger.error(f"get_mod_notes error: {e}", exc_info=True)
        return [], str(e)
    finally:
        cur.close()
        conn.close()
