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


def get_loan_history(username: str, role: str = "both", limit: int = 50, offset: int = 0):
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
            params = (username, limit, offset)
        elif role == "lender":
            where = "WHERE lender = %s"
            params = (username, limit, offset)
        else:  # both
            where = "WHERE borrower = %s OR lender = %s"
            params = (username, username, limit, offset)

        cur.execute(f'''
            SELECT id, loan_id, lender, borrower, amount, amount_repaid,
                   currency, status, date_created, original_thread, date_repaid
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
