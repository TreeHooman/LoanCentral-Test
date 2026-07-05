"""
LoanCentral API + Dashboard
----------------------------
- Reddit OAuth login (scope: identity only)
- Role-based dashboards: mod / lender / borrower
- REST API protected by session OR X-API-Key
"""

import json
import os
import secrets
import sys
import csv
import logging
import time
from io import StringIO
from datetime import datetime, timedelta
from decimal import Decimal
from functools import wraps

# Parent directory on path so we can import services / utils
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from flask import (Flask, flash, redirect, render_template,
                   request, session, url_for)

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))
app.permanent_session_lifetime = timedelta(days=7)

# Session cookie hardening — enforce in prod, relax in dev for localhost HTTP
_is_prod = os.getenv("LOANCENTRAL_ENV", "prod") == "prod"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = _is_prod  # HTTPS only in prod

API_KEY = os.getenv("API_KEY", "changeme")
# Master-key auth is disabled when API_KEY is unset or left at the insecure
# default — otherwise a missing env var would let anyone in with "changeme".
API_KEY_AUTH_ENABLED = bool(API_KEY) and API_KEY != "changeme"


def _api_key_ok(key):
    return API_KEY_AUTH_ENABLED and key == API_KEY
IS_DEV  = os.getenv("LOANCENTRAL_ENV", "prod") != "prod"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.getenv("UPLOAD_DIR", os.path.join(PROJECT_ROOT, "uploads"))

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("LoanCentral.api")
API_RATE_LIMIT_PER_MINUTE = int(os.getenv("API_RATE_LIMIT_PER_MINUTE", "120"))
_api_rate_hits = {}

# OTP brute-force protection — 5 attempts per IP per 15 minutes
OTP_RATE_WINDOW = 15 * 60   # seconds
OTP_RATE_MAX    = 5
_otp_attempts: dict = {}    # {ip: [timestamp, ...]}

def _otp_check_rate(ip: str) -> bool:
    """Return True if the IP is allowed, False if rate-limited. Cleans stale entries."""
    now = time.time()
    window_start = now - OTP_RATE_WINDOW
    hits = [t for t in _otp_attempts.get(ip, []) if t > window_start]
    if len(hits) >= OTP_RATE_MAX:
        _otp_attempts[ip] = hits
        return False
    hits.append(now)
    _otp_attempts[ip] = hits
    return True
MONEY_FIELDS = {"amount", "amount_repaid", "repay_amount", "remaining"}
PAYMENT_ROUTE_FIELDS = {"payment_method"}
MONEY_DETAIL_KEYS = {
    "amount", "amount_paid", "currency", "remaining", "loan_amount",
    "repay_amount", "amount_repaid", "payment_method",
}


def _looks_like_missing_column(error):
    msg = str(error).lower()
    return "does not exist" in msg and "column" in msg


# ---------------------------------------------------------------------------
# Version identifier (set BUILD_ID in env to a git SHA or deploy tag)
# ---------------------------------------------------------------------------
BUILD_ID = os.getenv("BUILD_ID", "dev")


# ---------------------------------------------------------------------------
# Centralized error logging
# ---------------------------------------------------------------------------

def log_request_error(exc: Exception, *, extra: str = ""):
    """
    Log a structured error record. Never exposes internal detail to end users.
    Fields: timestamp, method, path, user, role, remote_addr, exc_type, message, extra.
    Stack trace is always emitted at ERROR level so it appears in server logs.
    """
    logger.error(
        "request_error method=%s path=%s user=%s role=%s remote=%s exc=%s msg=%s%s",
        request.method,
        request.path,
        session.get("username", "anonymous"),
        session.get("role", "-"),
        request.remote_addr,
        type(exc).__name__,
        str(exc),
        f" extra={extra}" if extra else "",
        exc_info=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "0"  # modern browsers: rely on CSP not this
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )
    if _is_prod:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


@app.before_request
def require_public_dev_access():
    token = os.getenv("PUBLIC_DASHBOARD_TOKEN", "").strip()
    if not token or not IS_DEV:
        return None
    if request.path.startswith("/static/") or request.path == "/favicon.ico":
        return None
    if session.get("public_access_ok"):
        return None
    if request.args.get("access") == token:
        session["public_access_ok"] = True
        return redirect(request.path or url_for("login"))
    return app.response_class(
        "<h1>LoanCentral dev dashboard</h1><p>Access key required.</p>",
        status=403,
        mimetype="text/html",
    )


def _serial(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Not serializable: {type(obj)}")


def _json(data, status=200):
    return app.response_class(
        response=json.dumps(data, default=_serial),
        status=status,
        mimetype="application/json",
    )


def _date_only(value):
    if not value:
        return None
    if hasattr(value, "date"):
        return value.date()
    raw = str(value).split("T")[0]
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        return None


def _reminder_level(days_until):
    if days_until is None:
        return "missing_due_date"
    if days_until < 0:
        return "overdue"
    if days_until == 0:
        return "due_today"
    if days_until <= 3:
        return "due_soon"
    return "upcoming"


def _is_admin():
    return session.get("role") == "admin"


def _is_mod_or_admin():
    return session.get("role") in ("mod", "admin")


def _redact_money_value(value=None):
    return None


def _redact_loan_money(loan):
    if _is_admin():
        return loan
    clean = dict(loan)
    for field in MONEY_FIELDS | PAYMENT_ROUTE_FIELDS:
        if field in clean:
            clean[field] = _redact_money_value(clean.get(field))
    clean["money_redacted"] = True
    return clean


def _redact_loans_money(loans):
    if _is_admin():
        return loans
    return [_redact_loan_money(loan) for loan in loans]


def _redact_request_money(req):
    if _is_admin():
        return req
    clean = dict(req)
    for field in ("amount", "repay_amount", "payment_method"):
        if field in clean:
            clean[field] = _redact_money_value(clean.get(field))
    clean["money_redacted"] = True
    return clean


def _redact_activity_money(events):
    if _is_admin():
        return events
    redacted = []
    for event in events:
        clean = dict(event)
        details = clean.get("details")
        if isinstance(details, dict):
            clean["details"] = {
                key: ("redacted" if key in MONEY_DETAIL_KEYS else value)
                for key, value in details.items()
            }
        redacted.append(clean)
    return redacted


@app.before_request
def log_api_request():
    if request.path.startswith("/api/"):
        key = session.get("username") or request.headers.get("X-API-Key") or request.remote_addr or "unknown"
        now = time.time()
        window_start = now - 60
        hits = [ts for ts in _api_rate_hits.get(key, []) if ts >= window_start]
        if len(hits) >= API_RATE_LIMIT_PER_MINUTE:
            _api_rate_hits[key] = hits
            return _json({"error": "Too many API requests. Please slow down."}, 429)
        hits.append(now)
        _api_rate_hits[key] = hits
        # Periodic cleanup: drop keys with no recent hits to prevent unbounded growth
        if len(_api_rate_hits) > 500:
            stale = [k for k, v in _api_rate_hits.items() if not v or max(v) < window_start]
            for k in stale:
                del _api_rate_hits[k]
        logger.info(
            "api_request method=%s path=%s user=%s role=%s remote=%s",
            request.method,
            request.path,
            session.get("username", "api-key" if request.headers.get("X-API-Key") else "anonymous"),
            session.get("role", "-"),
            request.remote_addr,
        )


def _get_all_loans_from_db(status=None, search=None, limit=200):
    from services import _get_db
    conn = _get_db()
    if not conn:
        return None, "Database connection failed"
    try:
        cur = conn.cursor()
        conditions, params = [], []
        if status:
            conditions.append("status = %s")
            params.append(status)
        if search:
            conditions.append("(lender ILIKE %s OR borrower ILIKE %s OR loan_id ILIKE %s OR CAST(id AS TEXT) = %s OR notes ILIKE %s)")
            params += [f"%{search}%", f"%{search}%", f"%{search}%", search.strip(), f"%{search}%"]
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(limit)
        schema_mode = "dashboard"
        try:
            cur.execute(f"""
                SELECT id, loan_id, lender, borrower, amount, amount_repaid,
                       currency, status, date_created, original_thread, repay_date, notes, repay_amount,
                       payment_method, borrower_acknowledged_at, borrower_acknowledged_note
                FROM loans {where}
                ORDER BY date_created DESC LIMIT %s
            """, params)
        except Exception as e:
            if not _looks_like_missing_column(e):
                raise
            conn.rollback()
            schema_mode = "loan_id"
            try:
                cur.execute(f"""
                    SELECT id, loan_id, lender, borrower, amount, amount_repaid,
                           currency, status, date_created, original_thread
                    FROM loans {where}
                    ORDER BY date_created DESC LIMIT %s
                """, params)
            except Exception as inner:
                if not _looks_like_missing_column(inner):
                    raise
                conn.rollback()
                schema_mode = "base"
                cur.execute(f"""
                    SELECT id, lender, borrower, amount, amount_repaid,
                           currency, status, date_created, original_thread
                    FROM loans {where}
                    ORDER BY date_created DESC LIMIT %s
                """, params)
        rows = cur.fetchall()
        loans = []
        for r in rows:
            if schema_mode == "base":
                db_id, public_id = r[0], str(r[0])
                lender, borrower, amount, amount_repaid = r[1], r[2], r[3], r[4]
                currency, status, date_created, original_thread = r[5], r[6], r[7], r[8]
                repay_date, notes, raw_repay_amount, payment_method = None, None, None, None
                ack_at, ack_note = None, None
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
            repay_amount = raw_repay_amount if raw_repay_amount is not None else amount
            loans.append({
                "db_id": db_id, "loan_id": public_id, "lender": lender, "borrower": borrower,
                "amount": amount, "amount_repaid": amount_repaid, "currency": currency,
                "status": status, "date_created": date_created, "original_thread": original_thread,
                "repay_date": repay_date.isoformat() if repay_date else None,
                "notes": notes,
                "payment_method": payment_method,
                "borrower_acknowledged_at": ack_at.isoformat() if ack_at else None,
                "borrower_acknowledged_note": ack_note,
                "repay_amount": repay_amount,
                "remaining": Decimal(str(repay_amount)) - Decimal(str(amount_repaid)),
                "schema_outdated": schema_mode != "dashboard",
            })
        return loans, None
    except Exception as e:
        return None, str(e)
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Auth decorators
# ---------------------------------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("username"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not session.get("username"):
                return redirect(url_for("login"))
            if session.get("role") not in roles:
                flash("You don't have permission to access that page.", "error")
                return redirect(url_for("home"))
            return f(*args, **kwargs)
        return decorated
    return decorator


def require_auth(f):
    """API endpoints: accept X-API-Key header OR active session."""
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-API-Key")
        if _api_key_ok(key):
            return f(*args, **kwargs)
        if session.get("username"):
            return f(*args, **kwargs)
        return _json({"error": "Unauthorized. Provide X-API-Key header or log in."}, 401)
    return decorated


def require_mod_api(f):
    """API endpoints that mods/admins can call."""
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-API-Key")
        if _api_key_ok(key):
            return f(*args, **kwargs)
        if _is_mod_or_admin():
            return f(*args, **kwargs)
        return _json({"error": "Mod access required."}, 403)
    return decorated


def require_admin_api(f):
    """API endpoints that only owner/admin can call."""
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-API-Key")
        if _api_key_ok(key):
            return f(*args, **kwargs)
        if _is_admin():
            return f(*args, **kwargs)
        return _json({"error": "Admin access required."}, 403)
    return decorated


# ---------------------------------------------------------------------------
# Named permission decorators (Task 2)
# ---------------------------------------------------------------------------

def _get_perm_version(username: str) -> int:
    """Return the current perm_version for a user from the DB. Returns 0 on any error."""
    from services import _get_db
    conn = _get_db()
    if not conn:
        return 0
    try:
        cur = conn.cursor()
        cur.execute("SELECT perm_version FROM user_roles WHERE lower(username)=lower(%s)", (username,))
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return 0
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


def _is_lender_verified_fresh(username: str) -> bool:
    """Always queries the DB — used on sensitive POST actions to bypass session cache."""
    from services import get_verified_lender_status
    verified, _, _ = get_verified_lender_status(username)
    return verified


def verified_lender_required(f):
    """
    Requires verified lender, mod, or admin.
    Caches verification in session but re-checks DB when perm_version changes
    (e.g. after revocation) so staleness is bounded to one request.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("username"):
            return redirect(url_for("login"))
        role = session.get("role", "")
        if role in ("mod", "admin"):
            return f(*args, **kwargs)
        if role == "lender":
            username = session["username"]
            db_ver = _get_perm_version(username)
            if session.get("perm_version") != db_ver:
                # Permission record changed — re-check from DB and refresh cache.
                from services import get_verified_lender_status
                session["verified_lender"] = get_verified_lender_status(username)[0]
                session["perm_version"] = db_ver
            elif session.get("verified_lender") is None:
                from services import get_verified_lender_status
                session["verified_lender"] = get_verified_lender_status(username)[0]
                session["perm_version"] = db_ver
            if session.get("verified_lender"):
                return f(*args, **kwargs)
        flash("Verified lender access required.", "error")
        # Redirect to borrower dashboard — NOT home(), which would loop back here
        # for any session with role='lender'.
        return redirect(url_for("dashboard_borrower"))
    return decorated


# Aliases — built on role_required so any future auth-flow change propagates automatically.
mod_required   = role_required("mod", "admin")
admin_required = role_required("admin")


def _can_view_user_profile(target_username):
    key = request.headers.get("X-API-Key")
    if _api_key_ok(key):
        return True
    viewer = session.get("username")
    if not viewer:
        return False
    if _is_mod_or_admin():
        return True

    viewer = viewer.lower()
    target = target_username.lower()
    if viewer == target:
        return True

    from services import _get_db
    conn = _get_db()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 1 FROM loans
            WHERE (lender = %s AND borrower = %s)
               OR (lender = %s AND borrower = %s)
            LIMIT 1
        """, (viewer, target, target, viewer))
        return cur.fetchone() is not None
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    if not session.get("username"):
        return redirect(url_for("login"))
    role = session.get("role", "borrower")
    if role == "admin":
        return redirect(url_for("dashboard_admin"))
    if role == "mod":
        return redirect(url_for("dashboard_mod"))
    elif role == "lender":
        return redirect(url_for("dashboard_lender"))
    return redirect(url_for("dashboard_borrower"))


@app.route("/auth/key")
def auth_key():
    """Log in with a lender API key. GET /auth/key?k=<key>"""
    from services import validate_lender_key, get_user_role
    key = request.args.get("k", "").strip()
    if not key:
        flash("No key provided.", "error")
        return redirect(url_for("login"))
    username, error = validate_lender_key(key)
    if error or not username:
        flash("Invalid or revoked key. Contact your admin.", "error")
        return redirect(url_for("login"))
    role, _ = get_user_role(username)
    session["username"] = username
    session["role"] = role or "lender"
    session["auth_method"] = "key"
    return redirect(url_for("home"))


@app.route("/dashboard/admin/keys")
@role_required("admin")
def admin_keys_page():
    return render_template("admin_keys.html", username=session.get("username"))


@app.route("/api/admin/keys", methods=["GET"])
@require_admin_api
def api_list_keys():
    from services import list_lender_keys
    username_filter = request.args.get("username")
    rows, error = list_lender_keys(username=username_filter)
    if error:
        return _json({"error": error}, 500)
    return _json(rows)


@app.route("/api/admin/keys", methods=["POST"])
@role_required("admin")
def api_create_key():
    from services import create_lender_key, set_user_role
    data = request.get_json() or {}
    username = (data.get("username") or "").strip().lower()
    label = (data.get("label") or "").strip()
    if not username:
        return _json({"error": "username is required"}, 400)
    # Ensure user has at least lender role
    set_user_role(username, "lender")
    plaintext, error = create_lender_key(
        username=username,
        created_by=session.get("username", "admin"),
        label=label
    )
    if error:
        return _json({"error": error}, 500)
    return _json({"ok": True, "key": plaintext, "username": username})


@app.route("/api/admin/keys/<int:key_id>/revoke", methods=["POST"])
@role_required("admin")
def api_revoke_key(key_id):
    from services import revoke_lender_key
    ok, error = revoke_lender_key(key_id)
    if error:
        return _json({"error": error}, 500)
    return _json({"ok": True})


# ---------------------------------------------------------------------------
# Borrower OTP helpers
# ---------------------------------------------------------------------------

def _send_otp_email(to_address: str, code: str = None, *, link: str = None, username: str = None):
    import smtplib
    from email.message import EmailMessage
    host = os.getenv("SMTP_HOST", "")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "")
    pw   = os.getenv("SMTP_PASS", "")
    frm  = os.getenv("SMTP_FROM", user)
    if not host:
        raise RuntimeError("SMTP_HOST not configured.")
    msg = EmailMessage()
    if link:
        msg["Subject"] = "Your LoanCentral loan summary link"
        msg.set_content(
            f"Hi{' u/' + username if username else ''},\n\n"
            f"Here is your read-only LoanCentral loan dashboard link:\n\n  {link}\n\n"
            "This link expires in 7 days. It shows your loan history — nothing can be changed through it.\n\n"
            "If you didn't request this, you can ignore it."
        )
    else:
        msg["Subject"] = f"LoanCentral login code: {code}"
        msg.set_content(
            f"Your LoanCentral login code is:\n\n  {code}\n\n"
            "It expires in 10 minutes. If you didn't request this, ignore it."
        )
    msg["From"] = frm
    msg["To"]   = to_address
    with smtplib.SMTP(host, port) as s:
        s.starttls()
        if user:
            s.login(user, pw)
        s.send_message(msg)


def _send_otp_sms(to_number: str, code: str):
    sid   = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    frm   = os.getenv("TWILIO_FROM_NUMBER", "")
    if not sid or not token or not frm:
        raise RuntimeError("Twilio credentials not configured.")
    try:
        from twilio.rest import Client
    except ImportError:
        raise RuntimeError("twilio package not installed. Add it to requirements.txt.")
    client = Client(sid, token)
    client.messages.create(
        body=f"Your LoanCentral login code is {code}. Expires in 10 min.",
        from_=frm,
        to=to_number,
    )


# ---------------------------------------------------------------------------
# Borrower auth routes
# ---------------------------------------------------------------------------

@app.route("/login/borrower")
def borrower_login_page():
    return render_template("login_borrower.html")


@app.route("/api/auth/borrower/claim", methods=["POST"])
def api_borrower_claim():
    """Step 1: verify username+loan_id, send OTP to chosen contact."""
    if not _otp_check_rate(request.remote_addr):
        return _json({"error": "Too many attempts. Please wait 15 minutes and try again."}, 429)
    from services import (verify_borrower_loan_claim, get_borrower_contact,
                          create_borrower_otp, set_borrower_contact)
    data = request.get_json(silent=True) or {}
    username  = (data.get("username") or "").strip().lower()
    loan_id   = (data.get("loan_id") or "").strip()
    via       = (data.get("via") or "email").strip()          # 'email' | 'sms'
    new_email = (data.get("new_email") or "").strip() or None
    new_phone = (data.get("new_phone") or "").strip() or None

    if not username or not loan_id:
        return _json({"error": "Username and loan ID are required."}, 400)

    matched, err = verify_borrower_loan_claim(username, loan_id)
    if err:
        return _json({"error": err}, 500)
    if not matched:
        return _json({"error": "No loan found for that username and loan ID."}, 400)

    # Allow borrower to register contact info on first claim
    if new_email or new_phone:
        set_borrower_contact(username, contact_email=new_email, contact_phone=new_phone)

    email, phone = get_borrower_contact(username)

    if via == "sms":
        contact = phone
        if not contact:
            return _json({"error": "No phone number on file. Please provide one."}, 400)
    else:
        contact = email
        if not contact:
            return _json({"error": "No email address on file. Please provide one."}, 400)

    code, err = create_borrower_otp(username, contact, via)
    if err:
        return _json({"error": err}, 500)

    try:
        if via == "sms":
            _send_otp_sms(contact, code)
        else:
            _send_otp_email(contact, code)
    except Exception as e:
        logger.error(f"OTP send failed: {e}", exc_info=True)
        return _json({"error": f"Failed to send code: {e}"}, 500)

    masked = contact[:2] + "***" + contact[-4:] if len(contact) > 6 else "***"
    return _json({"ok": True, "masked": masked, "via": via})


@app.route("/api/auth/borrower/verify", methods=["POST"])
def api_borrower_verify():
    """Step 2: verify OTP, set session."""
    if not _otp_check_rate(request.remote_addr):
        return _json({"error": "Too many attempts. Please wait 15 minutes and try again."}, 429)
    from services import verify_borrower_otp, get_user_role, update_last_login
    data     = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    code     = (data.get("code") or "").strip()
    if not username or not code:
        return _json({"error": "Username and code are required."}, 400)
    ok, err = verify_borrower_otp(username, code)
    if not ok:
        return _json({"error": err or "Invalid code."}, 400)
    role, _ = get_user_role(username)
    session.permanent = True
    session["username"]    = username
    session["role"]        = role or "borrower"
    session["auth_method"] = "otp"
    update_last_login(username)
    return _json({"ok": True, "redirect": url_for("home")})


@app.route("/api/admin/borrower-contact/<username>", methods=["POST"])
@role_required("mod", "admin")
def api_set_borrower_contact(username):
    from services import set_borrower_contact
    data  = request.get_json(silent=True) or {}
    email = (data.get("contact_email") or "").strip() or None
    phone = (data.get("contact_phone") or "").strip() or None
    ok, err = set_borrower_contact(username, contact_email=email, contact_phone=phone)
    if not ok:
        return _json({"error": err}, 500)
    return _json({"ok": True})


# ---------------------------------------------------------------------------
# Magic link — mod sends, borrower views read-only dashboard
# ---------------------------------------------------------------------------

@app.route("/api/admin/send-magic-link/<username>", methods=["POST"])
@role_required("mod", "admin")
def api_send_magic_link(username):
    from services import create_magic_link, get_borrower_contact
    email, _ = get_borrower_contact(username)
    if not email:
        return _json({"error": "No email on file for this borrower. Set one first via the Roles panel."}, 400)
    token, err = create_magic_link(username)
    if err:
        return _json({"error": err}, 500)
    link = request.host_url.rstrip("/") + f"/view/{token}"
    try:
        _send_otp_email(email, None, link=link, username=username)
    except Exception as e:
        logger.error(f"Magic link email failed: {e}", exc_info=True)
        return _json({"error": f"Failed to send email: {e}"}, 500)
    return _json({"ok": True, "email": email})


@app.route("/view/<token>")
def borrower_view(token):
    from services import validate_magic_link, get_loan_history
    username, err = validate_magic_link(token)
    if err or not username:
        return render_template("link_expired.html"), 403
    loans, _ = get_loan_history(username, role="borrower", limit=200)
    return render_template("dashboard_borrower_readonly.html",
                           username=username, loans=loans or [], token=token)


@app.route("/view/<token>/calendar.ics")
def borrower_calendar(token):
    from services import validate_magic_link, get_loan_history
    username, err = validate_magic_link(token)
    if err or not username:
        return "Link invalid or expired.", 403
    loans, _ = get_loan_history(username, role="borrower", limit=200)
    ics = _build_ics(username, loans or [])
    from flask import Response
    return Response(ics, mimetype="text/calendar",
                    headers={"Content-Disposition": f'attachment; filename="loancentral-{username}.ics"'})


@app.route("/api/loans/<loan_id>/calendar.ics")
@require_auth
def loan_calendar_ics(loan_id):
    """Per-loan ICS download — accessible to the loan's lender or borrower."""
    from services import _get_db
    conn = _get_db()
    if not conn:
        return _json({"error": "Database connection failed"}, 500)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, loan_id, lender, borrower, amount, currency,
                   status, repay_date, repay_amount, original_thread
            FROM loans WHERE id::text = %s OR loan_id = %s
            ORDER BY id DESC LIMIT 1
        """, (loan_id, loan_id))
        row = cur.fetchone()
        if not row:
            return _json({"error": "Loan not found"}, 404)
        db_id, pub_id, lender, borrower, amount, currency, status, repay_date, repay_amount, thread = row
        pub_id = pub_id or str(db_id)
        # Scope check — only lender, borrower, or mod/admin
        if session.get("username") and not _is_mod_or_admin():
            me = session["username"]
            if lender != me and borrower != me:
                return _json({"error": "You can only export your own loans."}, 403)
        if not repay_date:
            return _json({"error": "This loan has no due date set."}, 400)
        due_str = str(repay_date)[:10].replace("-", "")
        due_amt = repay_amount or amount or 0
        import uuid as _uuid
        from datetime import datetime as _dt, timezone as _tz
        now_str = _dt.now(_tz.utc).strftime("%Y%m%dT%H%M%SZ")
        uid = str(_uuid.uuid4())
        summary = f"LoanCentral reminder: Loan {pub_id} due"
        desc = (f"LoanCentral loan {pub_id}\\n"
                f"Lender: u/{lender}\\n"
                f"Borrower: u/{borrower}\\n"
                f"Amount due: {due_amt} {currency}\\n"
                f"Status: {status}"
                + (f"\\nThread: {thread}" if thread and thread != "dashboard" else ""))
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//LoanCentral//Loan Due Dates//EN",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now_str}",
            f"DTSTART;VALUE=DATE:{due_str}",
            f"DTEND;VALUE=DATE:{due_str}",
            f"SUMMARY:{summary}",
            f"DESCRIPTION:{desc}",
            "BEGIN:VALARM",
            "TRIGGER:-P7D",
            "ACTION:DISPLAY",
            f"DESCRIPTION:7-day reminder: {summary}",
            "END:VALARM",
            "BEGIN:VALARM",
            "TRIGGER:-P1D",
            "ACTION:DISPLAY",
            f"DESCRIPTION:1-day reminder: {summary}",
            "END:VALARM",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
        ics = "\r\n".join(lines) + "\r\n"
        from flask import Response as _Response
        return _Response(ics, mimetype="text/calendar",
                         headers={"Content-Disposition": f'attachment; filename="loancentral-{pub_id}.ics"'})
    finally:
        try: cur.close()
        except: pass
        conn.close()


def _build_ics(username: str, loans: list) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//LoanCentral//Loan Due Dates//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    import uuid as _uuid
    from datetime import datetime as _dt, timezone as _tz
    now_str = _dt.now(_tz.utc).strftime("%Y%m%dT%H%M%SZ")
    for loan in loans:
        if not loan.get("repay_date") or loan.get("status") in ("repaid", "refunded"):
            continue
        try:
            due = str(loan["repay_date"])[:10].replace("-", "")  # YYYYMMDD
        except Exception:
            continue
        lid    = loan.get("loan_id") or loan.get("db_id") or "?"
        lender = loan.get("lender", "?")
        amount = loan.get("repay_amount") or loan.get("amount") or 0
        curr   = loan.get("currency", "USD")
        uid    = str(_uuid.uuid4())
        summary = f"Loan {lid} due — {amount} {curr} to u/{lender}"
        desc    = (f"LoanCentral loan {lid}\\n"
                   f"Lender: u/{lender}\\n"
                   f"Amount due: {amount} {curr}\\n"
                   f"Status: {loan.get('status','?')}")
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now_str}",
            f"DTSTART;VALUE=DATE:{due}",
            f"DTEND;VALUE=DATE:{due}",
            f"SUMMARY:{summary}",
            f"DESCRIPTION:{desc}",
            # 3-day reminder alarm
            "BEGIN:VALARM",
            "TRIGGER:-P3D",
            "ACTION:DISPLAY",
            f"DESCRIPTION:Reminder: {summary}",
            "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


@app.route("/api/admin/integrity")
@require_mod_api
def api_integrity_checks():
    from services import run_integrity_checks
    issues, error = run_integrity_checks()
    if error:
        return _json({"error": error}, 500)
    return _json(issues)


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/login")
def login():
    if session.get("username"):
        return redirect(url_for("home"))
    from api.auth import oauth_configured
    return render_template("login.html", oauth_ready=oauth_configured(), is_dev=IS_DEV)


@app.route("/auth/reddit")
def auth_reddit():
    from api.auth import check_rate_limit, get_auth_url, oauth_configured
    if not oauth_configured():
        flash("Reddit OAuth is not configured yet. Ask an admin.", "error")
        return redirect(url_for("login"))
    if not check_rate_limit(request.remote_addr):
        flash("Too many login attempts. Please wait 15 minutes.", "error")
        return redirect(url_for("login"))
    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state
    return redirect(get_auth_url(state))


@app.route("/auth/callback")
def auth_callback():
    from api.auth import exchange_code
    from services import get_user_role, update_last_login

    if request.args.get("error"):
        flash(f"Reddit login cancelled or denied.", "error")
        return redirect(url_for("login"))

    code  = request.args.get("code", "")
    state = request.args.get("state", "")

    if not code or state != session.pop("oauth_state", None):
        flash("Invalid login attempt. Please try again.", "error")
        return redirect(url_for("login"))

    username, err = exchange_code(code)
    if err:
        flash(f"Login failed: {err}", "error")
        return redirect(url_for("login"))

    role, _ = get_user_role(username)
    update_last_login(username)

    session.permanent = True
    session["username"] = username
    session["role"]     = role
    session["login_at"] = datetime.now().isoformat()

    return redirect(url_for("home"))


@app.route("/auth/dev-login", methods=["GET", "POST"])
def auth_dev_login():
    """Dev-only login bypass — disabled in production."""
    if not IS_DEV:
        return redirect(url_for("login"))
    if request.method == "POST":
        from services import get_user_role, set_user_role, update_last_login
        username = next((value.strip().lower() for value in request.form.getlist("username") if value.strip()), "")
        force_role = request.form.get("force_role", "").strip().lower()
        if username:
            if force_role in ("borrower", "lender", "mod", "admin"):
                set_user_role(username, force_role)
                role = force_role
            else:
                role, _ = get_user_role(username)
            update_last_login(username)
            session.permanent = True
            session["username"] = username
            session["role"]     = role
            session["login_at"] = datetime.now().isoformat()
            return redirect(url_for("home"))
    return render_template("dev_login.html")


@app.route("/auth/dev-login-as/<username>")
def auth_dev_login_as(username):
    """One-tap dev login for mobile/offline demo review."""
    if not IS_DEV:
        return redirect(url_for("login"))
    from services import get_user_role, update_last_login
    username = (username or "").strip().lower()
    if username:
        role, _ = get_user_role(username)
        update_last_login(username)
        session.permanent = True
        session["username"] = username
        session["role"] = role
        session["login_at"] = datetime.now().isoformat()
    return redirect(url_for("home"))


@app.route("/auth/logout")
def auth_logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard/mod")
@role_required("mod", "admin")
def dashboard_mod():
    return render_template("dashboard_mod.html",
                           username=session["username"],
                           role=session["role"],
                           can_view_money=False,
                           view_label="Mod Dashboard")


@app.route("/dashboard/admin")
@role_required("admin")
def dashboard_admin():
    return render_template("dashboard_mod.html",
                           username=session["username"],
                           role=session["role"],
                           can_view_money=True,
                           view_label="Admin Dashboard")


@app.route("/dashboard/lender")
@verified_lender_required
def dashboard_lender():
    return render_template("dashboard_lender.html",
                           username=session["username"],
                           role=session["role"],
                           verified_lender=session.get("verified_lender", False))


@app.route("/dashboard/borrower")
@login_required
def dashboard_borrower():
    return render_template("dashboard_borrower.html",
                           username=session["username"],
                           role=session["role"])


@app.route("/dashboard/users/<username>")
@login_required
def dashboard_user_profile(username):
    if not _can_view_user_profile(username):
        flash("You can only view profiles tied to your own loan history.", "error")
        return redirect(url_for("home"))
    return render_template("profile.html",
                           username=session["username"],
                           role=session["role"],
                           profile_username=username.lower())


# ---------------------------------------------------------------------------
# Admin: role management
# ---------------------------------------------------------------------------

@app.route("/api/admin/roles/<username>", methods=["GET"])
@require_mod_api
def get_role(username):
    from services import get_user_role
    role, err = get_user_role(username)
    if err:
        return _json({"error": err}, 500)
    return _json({"username": username, "role": role})


@app.route("/api/admin/roles/<username>", methods=["POST"])
@require_mod_api
def set_role(username):
    from services import set_user_role
    data = request.get_json() or {}
    role = data.get("role", "").strip().lower()
    if role == "admin" and not _is_admin():
        return _json({"error": "Only an admin can assign admin access."}, 403)
    result, err = set_user_role(username, role,
                                actor=session.get("username"),
                                actor_role=session.get("role"))
    if err:
        return _json({"error": err}, 400)
    return _json({"username": username, "role": role, "ok": True})


@app.route("/api/admin/roles", methods=["GET"])
@require_mod_api
def list_roles():
    from services import _get_db
    conn = _get_db()
    if not conn:
        return _json({"error": "Database connection failed"}, 500)
    limit  = min(int(request.args.get("limit", 500)), 1000)
    offset = int(request.args.get("offset", 0))
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT username, role, subscription_status, last_login, contact_email, contact_phone,
                   reddit_username
            FROM user_roles ORDER BY role, username LIMIT %s OFFSET %s
        """, (limit, offset))
        rows = cur.fetchall()
        return _json([
            {"username": r[0], "role": r[1], "subscription_status": r[2],
             "last_login": r[3], "contact_email": r[4], "contact_phone": r[5],
             "reddit_username": r[6]}
            for r in rows
        ])
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Loans API
# ---------------------------------------------------------------------------

@app.route("/api/loans", methods=["GET"])
@require_auth
def get_loans():
    from services import get_loan_history

    lender   = request.args.get("lender")
    borrower = request.args.get("borrower")
    status   = request.args.get("status")
    search   = request.args.get("search")
    limit    = int(request.args.get("limit", 200))

    # Non-mod/admins can only see their own data.
    if session.get("username") and not _is_mod_or_admin():
        me = session["username"]
        if lender and lender.lower() != me:
            return _json({"error": "You can only view your own loans."}, 403)
        if borrower and borrower.lower() != me:
            return _json({"error": "You can only view your own loans."}, 403)

    # Only mods/admins (or the trusted API key) may pull the whole loan book.
    privileged = _is_mod_or_admin() or _api_key_ok(request.headers.get("X-API-Key"))

    if lender:
        loans, error = get_loan_history(lender, role="lender", limit=limit)
        if not error and status:
            loans = [l for l in loans if l["status"] == status]
    elif borrower:
        loans, error = get_loan_history(borrower, role="borrower", limit=limit)
        if not error and status:
            loans = [l for l in loans if l["status"] == status]
    elif privileged:
        loans, error = _get_all_loans_from_db(status=status, search=search, limit=limit)
    else:
        # A regular user with no explicit filter only ever sees their own loans
        # (as lender or borrower) — never the whole platform.
        me = session.get("username", "")
        loans, error = get_loan_history(me, role="both", limit=limit)
        if not error and status:
            loans = [l for l in loans if l["status"] == status]

    if error:
        return _json({"error": error}, 500)

    # Add remaining to any loans missing it
    for loan in loans:
        if "remaining" not in loan:
            loan["remaining"] = float(loan["amount"]) - float(loan["amount_repaid"])

    if session.get("role") == "mod" and not (lender or borrower):
        loans = _redact_loans_money(loans)
    return _json(loans)


@app.route("/api/loans/export.csv", methods=["GET"])
@require_auth
def export_loans_csv():
    lender = request.args.get("lender")
    borrower = request.args.get("borrower")
    status = request.args.get("status")

    if not lender and not borrower:
        return _json({"error": "lender or borrower is required"}, 400)
    if session.get("username") and not _is_mod_or_admin():
        me = session["username"]
        if lender and lender.lower() != me:
            return _json({"error": "You can only export your own loans."}, 403)
        if borrower and borrower.lower() != me:
            return _json({"error": "You can only export your own loans."}, 403)

    from services import get_loan_history
    username = lender or borrower
    role = "lender" if lender else "borrower"
    loans, error = get_loan_history(username, role=role, limit=1000)
    if error:
        return _json({"error": error}, 500)
    if status:
        loans = [loan for loan in loans if loan["status"] == status]
    if session.get("role") == "mod":
        return _json({"error": "Admin access required to export loan money routes."}, 403)

    out = StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "loan_id", "lender", "borrower", "amount_lent", "repay_amount",
        "amount_repaid", "remaining", "currency", "status", "date_created",
        "repay_date", "payment_method", "interest_amount", "interest_rate",
        "borrower_acknowledged_at", "borrower_acknowledged_note", "thread", "notes"
    ])
    for loan in loans:
        writer.writerow([
            loan.get("loan_id") or loan.get("db_id"),
            loan.get("lender"),
            loan.get("borrower"),
            loan.get("amount"),
            loan.get("repay_amount", loan.get("amount")),
            loan.get("amount_repaid"),
            loan.get("remaining"),
            loan.get("currency"),
            loan.get("status"),
            loan.get("date_created"),
            loan.get("repay_date"),
            loan.get("payment_method") or "",
            loan.get("interest_amount") or "",
            loan.get("interest_rate") or "",
            loan.get("borrower_acknowledged_at") or "",
            loan.get("borrower_acknowledged_note") or "",
            loan.get("original_thread"),
            loan.get("notes") or "",
        ])

    filename = f"loancentral-{role}-{username}-loans.csv"
    return app.response_class(
        out.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.route("/api/loans/<loan_id>", methods=["GET"])
@require_auth
def get_loan(loan_id):
    from services import _get_db
    conn = _get_db()
    if not conn:
        return _json({"error": "Database connection failed"}, 500)
    try:
        cur = conn.cursor()
        schema_mode = "dashboard"
        try:
            cur.execute("""
                SELECT id, loan_id, lender, borrower, amount, amount_repaid,
                       currency, status, date_created, original_thread, repay_date, notes, repay_amount,
                       payment_method, borrower_acknowledged_at, borrower_acknowledged_note
                FROM loans WHERE id::text = %s OR loan_id = %s
                ORDER BY id DESC LIMIT 1
            """, (loan_id, loan_id))
        except Exception as e:
            if not _looks_like_missing_column(e):
                raise
            conn.rollback()
            schema_mode = "loan_id"
            try:
                cur.execute("""
                    SELECT id, loan_id, lender, borrower, amount, amount_repaid,
                           currency, status, date_created, original_thread
                    FROM loans WHERE id::text = %s OR loan_id = %s
                    ORDER BY id DESC LIMIT 1
                """, (loan_id, loan_id))
            except Exception as inner:
                if not _looks_like_missing_column(inner):
                    raise
                conn.rollback()
                schema_mode = "base"
                cur.execute("""
                    SELECT id, lender, borrower, amount, amount_repaid,
                           currency, status, date_created, original_thread
                    FROM loans WHERE id::text = %s
                    ORDER BY id DESC LIMIT 1
                """, (loan_id,))
        row = cur.fetchone()
        if not row:
            return _json({"error": "Loan not found"}, 404)
        if schema_mode == "base":
            db_id, public_id = row[0], str(row[0])
            lender, borrower, amount, amount_repaid = row[1], row[2], row[3], row[4]
            currency, status, date_created, original_thread = row[5], row[6], row[7], row[8]
            repay_date, notes, raw_repay_amount, payment_method = None, None, None, None
            ack_at, ack_note = None, None
        else:
            db_id, public_id = row[0], row[1] or str(row[0])
            lender, borrower, amount, amount_repaid = row[2], row[3], row[4], row[5]
            currency, status, date_created, original_thread = row[6], row[7], row[8], row[9]
            repay_date = row[10] if schema_mode == "dashboard" else None
            notes = row[11] if schema_mode == "dashboard" else None
            raw_repay_amount = row[12] if schema_mode == "dashboard" else None
            payment_method = row[13] if schema_mode == "dashboard" else None
            ack_at = row[14] if schema_mode == "dashboard" else None
            ack_note = row[15] if schema_mode == "dashboard" else None
        repay_amount = raw_repay_amount if raw_repay_amount is not None else amount
        loan = {
            "db_id": db_id, "loan_id": public_id, "lender": lender, "borrower": borrower,
            "amount": amount, "amount_repaid": amount_repaid, "currency": currency,
            "status": status, "date_created": date_created, "original_thread": original_thread,
            "repay_date": repay_date.isoformat() if repay_date else None,
            "notes": notes,
            "payment_method": payment_method,
            "borrower_acknowledged_at": ack_at.isoformat() if ack_at else None,
            "borrower_acknowledged_note": ack_note,
            "repay_amount": repay_amount,
            "remaining": Decimal(str(repay_amount)) - Decimal(str(amount_repaid)),
            "schema_outdated": schema_mode != "dashboard",
        }
        # Scope check
        if session.get("username") and not _is_mod_or_admin():
            me = session["username"]
            if loan["lender"] != me and loan["borrower"] != me:
                return _json({"error": "You can only view your own loans."}, 403)
        if session.get("role") == "mod":
            loan = _redact_loan_money(loan)
        return _json(loan)
    finally:
        cur.close()
        conn.close()


@app.route("/api/loans/<loan_id>/terms", methods=["PUT"])
@require_auth
def update_loan_terms(loan_id):
    from services import _get_db, log_event
    data = request.get_json() or {}
    repay_amount = data.get("repay_amount")
    repay_date = data.get("repay_date", "").strip()
    notes = (data.get("notes") or "").strip()
    interest_amount = data.get("interest_amount")
    interest_rate = data.get("interest_rate")

    if not repay_amount:
        return _json({"error": "repay_amount is required"}, 400)
    if not repay_date:
        return _json({"error": "repay_date is required"}, 400)

    try:
      repay_amount_dec = Decimal(str(repay_amount))
    except Exception:
        return _json({"error": "repay_amount must be a valid number"}, 400)
    if repay_amount_dec <= 0:
        return _json({"error": "repay_amount must be greater than zero"}, 400)
    try:
        interest_amount_dec = Decimal(str(interest_amount)) if interest_amount is not None else None
        interest_rate_dec = Decimal(str(interest_rate)) if interest_rate is not None else None
    except Exception:
        return _json({"error": "interest values must be valid numbers"}, 400)

    conn = _get_db()
    if not conn:
        return _json({"error": "Database connection failed"}, 500)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, lender, amount_repaid, status
            FROM loans
            WHERE id::text = %s OR loan_id = %s
            ORDER BY id DESC LIMIT 1
        """, (loan_id, loan_id))
        row = cur.fetchone()
        if not row:
            return _json({"error": "Loan not found"}, 404)

        db_id, lender, amount_repaid, status = row
        if session.get("username") and not _is_mod_or_admin():
            if lender != session["username"]:
                return _json({"error": "Only the lender can edit loan terms."}, 403)
        if status in ("repaid", "refunded"):
            return _json({"error": "Closed loans cannot be edited."}, 400)
        if repay_amount_dec < Decimal(str(amount_repaid or 0)):
            return _json({"error": "Repay amount cannot be less than amount already repaid."}, 400)

        cur.execute("""
            UPDATE loans
            SET repay_amount = %s,
                repay_date = %s,
                notes = COALESCE(NULLIF(%s, ''), notes),
                interest_amount = COALESCE(%s, interest_amount),
                interest_rate = COALESCE(%s, interest_rate),
                last_updated = NOW()
            WHERE id = %s
        """, (repay_amount_dec, repay_date, notes, interest_amount_dec, interest_rate_dec, db_id))
        conn.commit()
        log_event(
            "loan_terms_edited",
            actor=session.get("username"),
            actor_role=session.get("role"),
            loan_id=loan_id,
            source="dashboard",
            details={"repay_amount": str(repay_amount_dec), "repay_date": repay_date, "notes_saved": bool(notes)},
        )
        return _json({"ok": True, "loan_id": loan_id, "repay_amount": repay_amount_dec, "repay_date": repay_date, "notes": notes})
    except Exception as e:
        conn.rollback()
        if _looks_like_missing_column(e):
            return _json({"error": "Database migration required before editing loan terms."}, 400)
        return _json({"error": str(e)}, 500)
    finally:
        cur.close()
        conn.close()


@app.route("/api/loans/bulk-paid", methods=["POST"])
@require_auth
def bulk_mark_paid():
    from services import _get_db, mark_repaid
    data = request.get_json() or {}
    loan_ids = data.get("loan_ids") or []
    lender = data.get("lender", session.get("username", "")).strip().lower()

    if not lender:
        return _json({"error": "lender is required"}, 400)
    if not isinstance(loan_ids, list) or not loan_ids:
        return _json({"error": "loan_ids must be a non-empty list"}, 400)
    # Fresh DB check — bypass session cache on this write action.
    if session.get("role") == "lender" and not _is_lender_verified_fresh(lender):
        return _json({"error": "Verified lender access required."}, 403)
    if session.get("username") and not _is_mod_or_admin() and lender != session["username"]:
        return _json({"error": "You can only mark your own loans paid."}, 403)

    results = []
    errors = []
    for raw_id in loan_ids:
        loan_lookup = str(raw_id)
        conn = _get_db()
        if not conn:
            errors.append({"loan_id": loan_lookup, "error": "Database connection failed"})
            continue
        try:
            cur = conn.cursor()
            try:
                cur.execute("""
                    SELECT currency, amount_repaid, COALESCE(repay_amount, amount)
                    FROM loans
                    WHERE (id::text = %s OR loan_id = %s) AND lender = %s
                    ORDER BY id DESC LIMIT 1
                """, (loan_lookup, loan_lookup, lender))
            except Exception as e:
                if not _looks_like_missing_column(e):
                    raise
                conn.rollback()
                cur = conn.cursor()
                cur.execute("""
                    SELECT currency, amount_repaid, amount
                    FROM loans
                    WHERE id::text = %s AND lender = %s
                    ORDER BY id DESC LIMIT 1
                """, (loan_lookup, lender))
            row = cur.fetchone()
        finally:
            cur.close()
            conn.close()

        if not row:
            errors.append({"loan_id": loan_lookup, "error": "Loan not found for this lender"})
            continue
        currency, amount_repaid, repay_total = row
        remaining = Decimal(str(repay_total)) - Decimal(str(amount_repaid or 0))
        if remaining <= 0:
            errors.append({"loan_id": loan_lookup, "error": "Loan has no remaining balance"})
            continue
        result, error = mark_repaid(loan_lookup, remaining, currency, lender, actor_role="lender")
        if error:
            errors.append({"loan_id": loan_lookup, "error": error})
        else:
            results.append(result)

    return _json({"ok": not errors, "updated": results, "errors": errors}, 207 if errors else 200)


@app.route("/api/loans/<loan_id>/unpaid", methods=["POST"])
@require_auth
def set_loan_unpaid(loan_id):
    from services import mark_unpaid
    data   = request.get_json() or {}
    lender = data.get("lender", session.get("username", "")).strip().lower()
    if not lender:
        return _json({"error": "lender is required"}, 400)
    if session.get("role") == "lender" and not _is_lender_verified_fresh(lender):
        return _json({"error": "Verified lender access required."}, 403)
    result, error = mark_unpaid(loan_id, lender)
    if error:
        return _json({"error": error}, 400)
    return _json(result)


@app.route("/api/loans/<loan_id>/refunded", methods=["POST"])
@require_auth
def set_loan_refunded(loan_id):
    from services import mark_refunded_by_id
    data   = request.get_json() or {}
    lender = data.get("lender", session.get("username", "")).strip().lower()
    if not lender:
        return _json({"error": "lender is required"}, 400)
    if session.get("role") == "lender" and not _is_lender_verified_fresh(lender):
        return _json({"error": "Verified lender access required."}, 403)
    result, error = mark_refunded_by_id(loan_id, lender)
    if error:
        return _json({"error": error}, 400)
    return _json(result)


@app.route("/api/loans/<loan_id>/dispute", methods=["POST"])
@require_auth
def set_loan_disputed(loan_id):
    from services import dispute_loan
    data     = request.get_json() or {}
    borrower = data.get("borrower", session.get("username", "")).strip().lower()
    if not borrower:
        return _json({"error": "borrower is required"}, 400)
    result, error = dispute_loan(loan_id, borrower)
    if error:
        return _json({"error": error}, 400)
    return _json(result)


@app.route("/api/loans/<loan_id>/acknowledge", methods=["POST"])
@require_auth
def acknowledge_loan(loan_id):
    from services import _get_db, log_event
    data = request.get_json() or {}
    note = (data.get("note") or "").strip()
    borrower = session.get("username", "").strip().lower()
    if not borrower:
        return _json({"error": "borrower login is required"}, 400)

    conn = _get_db()
    if not conn:
        return _json({"error": "Database connection failed"}, 500)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, lender, borrower, status, borrower_acknowledged_at
            FROM loans
            WHERE id::text = %s OR loan_id = %s
            ORDER BY id DESC LIMIT 1
        """, (loan_id, loan_id))
        row = cur.fetchone()
        if not row:
            return _json({"error": "Loan not found"}, 404)

        db_id, lender, loan_borrower, status, ack_at = row
        if not _is_mod_or_admin() and loan_borrower != borrower:
            return _json({"error": "Only the borrower can acknowledge this loan."}, 403)
        if status in ("refunded",):
            return _json({"error": "Refunded loans cannot be acknowledged."}, 400)
        if ack_at:
            return _json({"error": "Loan already acknowledged."}, 400)

        cur.execute("""
            UPDATE loans
            SET borrower_acknowledged_at = %s,
                borrower_acknowledged_note = %s,
                last_updated = %s
            WHERE id = %s
        """, (datetime.now(), note or None, datetime.now(), db_id))
        conn.commit()
        log_event(
            "loan_acknowledged",
            actor=borrower,
            actor_role=session.get("role"),
            target_user=lender,
            loan_id=loan_id,
            source="dashboard",
            details={"note_length": len(note), "status": status},
        )
        return _json({"ok": True, "loan_id": loan_id, "acknowledged": True})
    except Exception as e:
        conn.rollback()
        if _looks_like_missing_column(e):
            return _json({"error": "Database migration required before acknowledging loans."}, 400)
        return _json({"error": str(e)}, 500)
    finally:
        cur.close()
        conn.close()


@app.route("/api/loans/<loan_id>/report-payment", methods=["POST"])
@require_auth
def report_payment(loan_id):
    """Borrower self-reports a payment — stored as a note, does not change loan status."""
    from services import _get_db, log_event
    data = request.get_json() or {}
    amount = data.get("amount")
    currency = (data.get("currency") or "USD").strip().upper()
    note = (data.get("note") or "").strip()
    borrower = session.get("username", "").strip().lower()

    if not amount or float(amount) <= 0:
        return _json({"error": "amount is required"}, 400)

    conn = _get_db()
    if not conn:
        return _json({"error": "Database connection failed"}, 500)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, borrower, lender, status
            FROM loans WHERE id::text = %s OR loan_id = %s
            ORDER BY id DESC LIMIT 1
        """, (loan_id, loan_id))
        row = cur.fetchone()
        if not row:
            return _json({"error": "Loan not found"}, 404)
        db_id, loan_borrower, lender, status = row
        if loan_borrower != borrower:
            return _json({"error": "Only the borrower can report a payment on this loan."}, 403)
        if status in ("repaid", "refunded"):
            return _json({"error": "This loan is already closed."}, 400)

        report_text = f"[Borrower payment report] {float(amount):.2f} {currency} sent."
        if note:
            report_text += f" Note: {note}"

        cur.execute("""
            UPDATE loans
            SET notes = CASE
                WHEN notes IS NULL OR notes = '' THEN %s
                ELSE notes || E'\n' || %s
            END,
            last_updated = NOW()
            WHERE id = %s
        """, (report_text, report_text, db_id))
        conn.commit()
        log_event(
            "borrower_payment_reported",
            actor=borrower,
            actor_role=session.get("role"),
            target_user=lender,
            loan_id=loan_id,
            source="dashboard",
            details={"amount": str(amount), "currency": currency, "note": note}
        )
        return _json({"ok": True})
    except Exception as e:
        conn.rollback()
        return _json({"error": str(e)}, 500)
    finally:
        cur.close()
        conn.close()


@app.route("/api/loans/<loan_id>/paid", methods=["POST"])
@require_auth
def set_loan_paid(loan_id):
    from services import mark_repaid
    data     = request.get_json() or {}
    lender   = data.get("lender", session.get("username", "")).strip().lower()
    amount   = data.get("amount")
    currency = data.get("currency", "").upper()
    timing   = data.get("timing")  # 'early', 'late', 'on_time', or None
    if not all([lender, amount, currency]):
        return _json({"error": "lender, amount, and currency are required"}, 400)
    if session.get("role") == "lender" and not _is_lender_verified_fresh(lender):
        return _json({"error": "Verified lender access required."}, 403)
    result, error = mark_repaid(loan_id, Decimal(str(amount)), currency, lender, actor_role="lender", payment_timing=timing)
    if error:
        return _json({"error": error}, 400)
    return _json(result)


# ---------------------------------------------------------------------------
# Users API
# ---------------------------------------------------------------------------

@app.route("/api/users/<username>", methods=["GET"])
@require_auth
def get_user(username):
    from services import get_user_profile, get_loan_history
    if not _can_view_user_profile(username):
        return _json({"error": "You can only view profiles tied to your own loan history."}, 403)
    profile, error = get_user_profile(username)
    if error:
        return _json({"error": error}, 500)
    loans, _ = get_loan_history(username, role="both", limit=50)
    if session.get("role") == "mod":
        profile = dict(profile)
        for field in ("amount_borrowed", "amount_lent", "amount_repaid", "unpaid_amount", "active_amount"):
            if field in profile:
                profile[field] = None
        loans = _redact_loans_money(loans or [])
    profile["recent_loans"] = loans or []
    return _json(profile)


@app.route("/api/users/me", methods=["GET"])
@login_required
def get_me():
    return redirect(url_for("get_user", username=session["username"]))


@app.route("/api/session", methods=["GET"])
@login_required
def get_session_status():
    login_at_raw = session.get("login_at")
    try:
        login_at = datetime.fromisoformat(login_at_raw) if login_at_raw else datetime.now()
    except ValueError:
        login_at = datetime.now()
    expires_at = login_at + app.permanent_session_lifetime
    seconds_remaining = max(0, int((expires_at - datetime.now()).total_seconds()))
    return _json({
        "username": session.get("username"),
        "role": session.get("role"),
        "login_at": login_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "seconds_remaining": seconds_remaining,
    })


@app.route("/api/integrations/reddit/status", methods=["GET"])
@require_mod_api
def reddit_integration_status():
    """Report live Reddit action switches. This endpoint never calls Reddit."""
    return _json({
        "reminder_reddit_enabled": os.getenv("REMINDER_REDDIT_ENABLED", "false").lower() in ("1", "true", "yes"),
        "auto_ban_reddit_enabled": os.getenv("AUTO_BAN_REDDIT_ENABLED", "false").lower() in ("1", "true", "yes"),
        "reddit_flair_sync_enabled": os.getenv("REDDIT_FLAIR_SYNC_ENABLED", "false").lower() in ("1", "true", "yes"),
        "configured_subreddits": os.getenv("SUBREDDITS", ""),
        "oauth_configured": bool(os.getenv("DASHBOARD_CLIENT_ID") and os.getenv("DASHBOARD_CLIENT_SECRET")),
        "mode": "safe" if IS_DEV else "production",
    })


@app.route("/api/reddit-actions", methods=["GET"])
@require_mod_api
def get_reddit_actions():
    from services import list_reddit_actions
    rows, error = list_reddit_actions(
        status=request.args.get("status"),
        action_type=request.args.get("action_type"),
        limit=int(request.args.get("limit", 100)),
    )
    if error:
        return _json({"error": error}, 500)
    return _json(rows)


@app.route("/api/reddit-actions/ban", methods=["POST"])
@require_mod_api
def queue_reddit_ban():
    from services import enqueue_reddit_action
    data = request.get_json() or {}
    target_user = (data.get("target_user") or "").strip().lower()
    loan_id = (data.get("loan_id") or "").strip()
    reason = (data.get("reason") or "").strip() or "Mod confirmed unpaid/default review."
    if not target_user:
        return _json({"error": "target_user is required"}, 400)
    result, error = enqueue_reddit_action(
        "ban_user",
        target_user=target_user,
        loan_id=loan_id or None,
        subreddit=os.getenv("PRIMARY_SUBREDDIT") or (os.getenv("SUBREDDITS", "").split(",")[0].strip() or None),
        payload={"ban_message": reason},
        reason=reason,
        created_by=session.get("username", "api-key"),
    )
    if error:
        return _json({"error": error}, 400)
    return _json(result)


@app.route("/api/reddit-actions/<int:action_id>/status", methods=["POST"])
@require_mod_api
def set_reddit_action_status(action_id):
    from services import update_reddit_action_status
    data = request.get_json() or {}
    result, error = update_reddit_action_status(
        action_id,
        status=data.get("status", ""),
        actor=session.get("username", "api-key"),
        reason=(data.get("reason") or "").strip(),
    )
    if error:
        return _json({"error": error}, 400)
    return _json(result)


# ---------------------------------------------------------------------------
# Stats API
# ---------------------------------------------------------------------------

@app.route("/api/stats", methods=["GET"])
@require_auth
def get_stats():
    from services import _get_db
    conn = _get_db()
    if not conn:
        return _json({"error": "Database connection failed"}, 500)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                COUNT(*)                                                     AS total,
                COUNT(*) FILTER (WHERE status = 'confirmed')                AS active,
                COUNT(*) FILTER (WHERE status = 'partially_repaid')         AS partial,
                COUNT(*) FILTER (WHERE status = 'unpaid')                   AS unpaid,
                COUNT(*) FILTER (WHERE status = 'repaid')                   AS repaid,
                COUNT(*) FILTER (WHERE status = 'refunded')                 AS refunded,
                COUNT(*) FILTER (WHERE status = 'disputed')                 AS disputed,
                COALESCE(SUM(amount), 0)                                    AS total_volume,
                COALESCE(SUM(amount_repaid), 0)                             AS total_repaid,
                COALESCE(SUM(amount) FILTER (
                    WHERE status IN ('confirmed','partially_repaid','unpaid')), 0) AS outstanding
            FROM loans
        """)
        row = cur.fetchone()
        stats = {
            "total_loans":    row[0], "active_loans":  row[1],
            "partial_loans":  row[2], "unpaid_loans":  row[3],
            "repaid_loans":   row[4], "refunded_loans": row[5],
            "disputed_loans": row[6],
            "total_volume":   row[7], "total_repaid":  row[8],
            "outstanding":    row[9],
        }
        if session.get("role") == "mod":
            stats["total_volume"] = None
            stats["total_repaid"] = None
            stats["outstanding"] = None
            stats["money_redacted"] = True
        return _json(stats)
    finally:
        cur.close()
        conn.close()


@app.route("/api/stats/lender/<lender>", methods=["GET"])
@require_auth
def get_lender_stats(lender):
    from services import get_lender_stats
    if session.get("username") and not _is_mod_or_admin():
        if lender.lower() != session["username"]:
            return _json({"error": "You can only view your own stats."}, 403)
    stats, error = get_lender_stats(lender)
    if error:
        return _json({"error": error}, 500)
    if session.get("role") == "mod" and lender.lower() != session.get("username", "").lower():
        stats["total_lent"] = None
        stats["total_recovered"] = None
        stats["outstanding"] = None
        stats["money_redacted"] = True
    return _json(stats)


@app.route("/api/activity", methods=["GET"])
@require_mod_api
def get_activity():
    from services import get_recent_activity
    limit = int(request.args.get("limit", 50))
    events, error = get_recent_activity(limit=limit)
    if error:
        return _json({"error": error}, 500)
    if session.get("role") == "mod":
        events = _redact_activity_money(events)
    return _json(events)


@app.route("/api/verification", methods=["GET"])
@require_mod_api
def get_verification_applications():
    from services import list_verification_applications
    status = request.args.get("status")
    limit = int(request.args.get("limit", 100))
    rows, error = list_verification_applications(status=status, limit=limit)
    if error:
        return _json({"error": error}, 500)
    return _json(rows)


@app.route("/api/verification/apply", methods=["POST"])
@require_auth
def apply_verification():
    from services import submit_verification_application
    data = request.get_json() or {}
    username = session.get("username") or data.get("username", "")
    result, error = submit_verification_application(
        username=username,
        requested_role=data.get("requested_role", "lender"),
        public_note=(data.get("public_note") or "").strip(),
        private_note=(data.get("private_note") or "").strip(),
    )
    if error:
        return _json({"error": error}, 400)
    return _json(result)


@app.route("/api/verification/<int:application_id>/decision", methods=["POST"])
@require_mod_api
def decide_verification(application_id):
    from services import decide_verification_application
    data = request.get_json() or {}
    result, error = decide_verification_application(
        application_id=application_id,
        decision=data.get("decision", ""),
        reviewer=session.get("username", "api-key"),
        review_note=(data.get("review_note") or "").strip(),
    )
    if error:
        return _json({"error": error}, 400)
    return _json(result)


@app.route("/api/reminders", methods=["GET"])
@require_auth
def get_reminders():
    """Read-only due-date queue for dashboard reminders. Does not call Reddit."""
    lender = (request.args.get("lender") or "").strip().lower()
    limit = min(max(int(request.args.get("limit", 200)), 1), 500)
    days = min(max(int(request.args.get("days", 3)), 0), 30)

    if session.get("username") and not _is_mod_or_admin():
        lender = session["username"]

    loans, error = _get_all_loans_from_db(limit=limit)
    if error:
        return _json({"error": error}, 500)

    today = datetime.now().date()
    open_statuses = {"confirmed", "partially_repaid", "unpaid", "disputed"}
    items = []
    counts = {"overdue": 0, "due_today": 0, "due_soon": 0, "missing_due_date": 0, "upcoming": 0}

    for loan in loans:
        if lender and str(loan.get("lender", "")).lower() != lender:
            continue
        if loan.get("status") not in open_statuses:
            continue
        repay_amount = Decimal(str(loan.get("repay_amount") or loan.get("amount") or 0))
        amount_repaid = Decimal(str(loan.get("amount_repaid") or 0))
        remaining = repay_amount - amount_repaid
        if remaining <= 0:
            continue
        due_date = _date_only(loan.get("repay_date"))
        days_until = (due_date - today).days if due_date else None
        level = _reminder_level(days_until)
        if level == "upcoming" and (days_until is None or days_until > days):
            continue
        counts[level] = counts.get(level, 0) + 1
        items.append({
            "loan_id": loan.get("loan_id") or loan.get("db_id"),
            "db_id": loan.get("db_id"),
            "lender": loan.get("lender"),
            "borrower": loan.get("borrower"),
            "status": loan.get("status"),
            "amount": loan.get("amount"),
            "repay_amount": repay_amount,
            "amount_repaid": amount_repaid,
            "remaining": remaining,
            "currency": loan.get("currency"),
            "repay_date": loan.get("repay_date"),
            "days_until_due": days_until,
            "level": level,
            "thread": loan.get("original_thread"),
            "payment_method": loan.get("payment_method"),
        })

    rank = {"overdue": 0, "due_today": 1, "due_soon": 2, "missing_due_date": 3, "upcoming": 4}
    items.sort(key=lambda item: (
        rank.get(item["level"], 9),
        item["days_until_due"] if item["days_until_due"] is not None else 9999,
        -float(item["remaining"]),
    ))
    if session.get("role") == "mod":
        for item in items:
            for field in MONEY_FIELDS | PAYMENT_ROUTE_FIELDS:
                if field in item:
                    item[field] = None
            item["money_redacted"] = True

    return _json({
        "items": items,
        "counts": counts,
        "window_days": days,
        "lender": lender or None,
    })


# ---------------------------------------------------------------------------
# Loan Requests API
# ---------------------------------------------------------------------------

@app.route("/api/loans/<loan_id>/clear-unpaid", methods=["POST"])
@require_mod_api
def clear_unpaid(loan_id):
    from services import _get_db, log_event
    data   = request.get_json() or {}
    lender = data.get("lender", "").strip().lower()
    conn   = _get_db()
    if not conn:
        return _json({"error": "Database connection failed"}, 500)
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE loans SET status = 'confirmed', last_updated = NOW()
            WHERE (id::text = %s OR loan_id = %s) AND status = 'unpaid'
        """, (loan_id, loan_id))
        if cur.rowcount == 0:
            return _json({"error": "Loan not found or not in unpaid status"}, 404)
        conn.commit()
        log_event(
            "unpaid_cleared",
            actor=session.get("username"),
            actor_role=session.get("role"),
            loan_id=loan_id,
            source="dashboard",
            details={"lender": lender},
        )
        return _json({"ok": True})
    except Exception as e:
        conn.rollback()
        if _looks_like_missing_column(e):
            return _json({"error": "Database migration required before saving notes."}, 400)
        return _json({"error": str(e)}, 500)
    finally:
        cur.close()
        conn.close()


@app.route("/api/loans/<loan_id>/notes", methods=["POST"])
@require_auth
def save_note(loan_id):
    from services import _get_db, log_event
    data = request.get_json() or {}
    note = data.get("note", "").strip()
    conn = _get_db()
    if not conn:
        return _json({"error": "Database connection failed"}, 500)
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE loans SET notes = %s, last_updated = NOW()
            WHERE id::text = %s OR loan_id = %s
        """, (note or None, loan_id, loan_id))
        conn.commit()
        log_event(
            "loan_note_updated",
            actor=session.get("username"),
            actor_role=session.get("role"),
            loan_id=loan_id,
            source="dashboard",
            details={"note_length": len(note)},
        )
        return _json({"ok": True})
    except Exception as e:
        conn.rollback()
        if _looks_like_missing_column(e):
            return _json({"error": "Database migration required before saving notes."}, 400)
        return _json({"error": str(e)}, 500)
    finally:
        cur.close()
        conn.close()


@app.route("/api/loans/<loan_id>/attachments", methods=["GET"])
@require_auth
def get_attachments(loan_id):
    from services import _get_db
    conn = _get_db()
    if not conn:
        return _json({"error": "Database connection failed"}, 500)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, filename, original_name, file_size, mime_type, uploaded_by, uploaded_at
            FROM loan_attachments WHERE loan_id = %s ORDER BY uploaded_at
        """, (loan_id,))
        rows = cur.fetchall()
        return _json([{
            "id": r[0], "filename": r[1], "original_name": r[2],
            "file_size": r[3], "mime_type": r[4],
            "uploaded_by": r[5], "uploaded_at": r[6].isoformat() if r[6] else None,
            "url": f"/api/loans/{loan_id}/attachments/{r[0]}/download"
        } for r in rows])
    except Exception as e:
        if _looks_like_missing_column(e) or "loan_attachments" in str(e):
            return _json({"error": "Database migration required before using attachments."}, 400)
        return _json({"error": str(e)}, 500)
    finally:
        cur.close()
        conn.close()


@app.route("/api/loans/<loan_id>/attachments", methods=["POST"])
@require_auth
def upload_attachment(loan_id):
    import uuid, pathlib
    from services import _get_db
    from flask import send_from_directory
    if "file" not in request.files:
        return _json({"error": "No file provided"}, 400)
    f = request.files["file"]
    if not f.filename:
        return _json({"error": "Empty filename"}, 400)
    allowed = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf", ".txt", ".csv"}
    ext = pathlib.Path(f.filename).suffix.lower()
    if ext not in allowed:
        return _json({"error": f"File type {ext} not allowed"}, 400)
    upload_dir = UPLOAD_DIR
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex}{ext}"
    f.save(os.path.join(upload_dir, safe_name))
    size = os.path.getsize(os.path.join(upload_dir, safe_name))
    conn = _get_db()
    if not conn:
        return _json({"error": "Database connection failed"}, 500)
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO loan_attachments (loan_id, uploaded_by, filename, original_name, file_size, mime_type)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
        """, (loan_id, session.get("username", "unknown"), safe_name, f.filename, size, f.content_type))
        att_id = cur.fetchone()[0]
        conn.commit()
        return _json({"ok": True, "id": att_id, "original_name": f.filename,
                      "url": f"/api/loans/{loan_id}/attachments/{att_id}/download"})
    except Exception as e:
        conn.rollback()
        if _looks_like_missing_column(e) or "loan_attachments" in str(e):
            return _json({"error": "Database migration required before using attachments."}, 400)
        return _json({"error": str(e)}, 500)
    finally:
        cur.close()
        conn.close()


@app.route("/api/loans/<loan_id>/attachments/<int:att_id>/download")
@require_auth
def download_attachment(loan_id, att_id):
    from flask import send_from_directory
    from services import _get_db
    conn = _get_db()
    if not conn:
        return _json({"error": "Database connection failed"}, 500)
    try:
        cur = conn.cursor()
        cur.execute("SELECT filename, original_name FROM loan_attachments WHERE id = %s AND loan_id = %s",
                    (att_id, loan_id))
        row = cur.fetchone()
        if not row:
            return _json({"error": "Not found"}, 404)
        upload_dir = UPLOAD_DIR
        return send_from_directory(upload_dir, row[0], download_name=row[1])
    finally:
        cur.close()
        conn.close()


@app.route("/api/loans/create", methods=["POST"])
@require_auth
def create_loan_manual():
    from services import create_loan
    data        = request.get_json() or {}
    lender      = session.get("username", "").strip().lower()
    borrower    = data.get("borrower", "").strip().lower()
    # Dashboard loan creation requires verified lender (same rule as bot).
    if session.get("role") == "lender" and not _is_lender_verified_fresh(lender):
        return _json({"error": "Verified lender access required."}, 403)
    amount      = data.get("amount")
    currency    = data.get("currency", "USD").strip().upper()
    repay_amount = data.get("repay_amount")
    repay_date   = data.get("repay_date", "").strip()
    thread_link = data.get("thread_link", "").strip()
    payment_method = data.get("payment_method", "").strip()
    interest_amount = data.get("interest_amount")
    interest_rate   = data.get("interest_rate")
    if not all([lender, borrower, amount]):
        return _json({"error": "borrower and amount are required"}, 400)
    if not repay_amount:
        return _json({"error": "repay_amount is required"}, 400)
    if not repay_date:
        return _json({"error": "repay_date is required"}, 400)
    if lender == borrower:
        return _json({"error": "You cannot loan to yourself."}, 400)
    loan_id, error = create_loan(
        lender, borrower, Decimal(str(amount)), currency, thread_link or "dashboard",
        repay_amount=Decimal(str(repay_amount)), repay_date=repay_date, payment_method=payment_method,
        interest_amount=Decimal(str(interest_amount)) if interest_amount is not None else None,
        interest_rate=Decimal(str(interest_rate)) if interest_rate is not None else None,
    )
    if error:
        return _json({"error": error}, 400)
    return _json({"ok": True, "loan_id": loan_id, "paid_id": loan_id})


@app.route("/api/requests", methods=["GET"])
@require_auth
def list_requests():
    from services import expire_old_requests, get_open_requests
    if os.getenv("AUTO_EXPIRE_REQUESTS_ON_READ", "yes").lower() in ("1", "true", "yes"):
        expire_old_requests()
    requests, error = get_open_requests(limit=200)
    if error:
        return _json({"error": error}, 500)
    if session.get("role") == "mod":
        requests = [_redact_request_money(item) for item in requests]
    return _json(requests)


@app.route("/api/requests/expire", methods=["POST"])
@require_mod_api
def expire_requests():
    from services import expire_old_requests
    data = request.get_json() or {}
    days = data.get("days")
    count, error = expire_old_requests(days=int(days) if days else None)
    if error:
        return _json({"error": error}, 500)
    return _json({"ok": True, "expired": count})


@app.route("/api/requests/<request_id>", methods=["GET"])
@require_auth
def get_request(request_id):
    from services import find_duplicate_open_requests, get_loan_request
    req, error = get_loan_request(request_id)
    if error:
        return _json({"error": error}, 404)
    duplicates, dup_error = find_duplicate_open_requests(
        req.get("borrower", ""),
        exclude_request_id=req.get("request_id"),
    )
    if not dup_error:
        req["duplicate_open_request_count"] = len(duplicates)
        req["duplicate_open_request_ids"] = [item["request_id"] for item in duplicates]
    if session.get("role") == "mod":
        req = _redact_request_money(req)
    return _json(req)


@app.route("/api/requests/<request_id>/note", methods=["POST"])
@require_auth
def note_request(request_id):
    from services import _get_db, get_loan_request, log_event
    data = request.get_json() or {}
    note = data.get("note", "").strip()
    if not note:
        return _json({"error": "note is required"}, 400)

    req, error = get_loan_request(request_id)
    if error:
        return _json({"error": error}, 404)
    if session.get("role") not in ("lender", "mod", "admin"):
        return _json({"error": "Only lenders or mods can note requests."}, 403)

    conn = _get_db()
    if not conn:
        return _json({"error": "Database connection failed"}, 500)
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE loan_requests
            SET lender_note = %s
            WHERE request_id = %s
        """, (note, request_id.upper()))
        conn.commit()
        log_event(
            "request_note_added",
            actor=session.get("username"),
            actor_role=session.get("role"),
            target_user=req.get("borrower"),
            request_id=request_id.upper(),
            source="dashboard",
            details={"note_length": len(note)},
        )
        return _json({"ok": True})
    except Exception as e:
        conn.rollback()
        return _json({"error": str(e)}, 500)
    finally:
        cur.close()
        conn.close()


@app.route("/api/requests/<request_id>/fund", methods=["POST"])
@require_auth
def fund_request(request_id):
    from services import fund_loan_request
    data        = request.get_json() or {}
    lender      = data.get("lender", session.get("username", "")).strip().lower()
    repay_amount = data.get("repay_amount")
    repay_date   = data.get("repay_date", "").strip()
    if not lender:
        return _json({"error": "lender is required"}, 400)
    if not repay_amount:
        return _json({"error": "repay_amount is required"}, 400)
    if not repay_date:
        return _json({"error": "repay_date is required"}, 400)
    loan_id, error = fund_loan_request(request_id, lender, float(repay_amount), repay_date)
    if error:
        return _json({"error": error}, 400)
    return _json({"ok": True, "loan_id": loan_id, "paid_id": loan_id, "request_id": request_id})


@app.route("/api/requests/<request_id>/cancel", methods=["POST"])
@require_auth
def cancel_request(request_id):
    from services import cancel_loan_request
    if session.get("role") not in ("lender", "mod", "admin"):
        return _json({"error": "Only lenders or mods can cancel a looked-up request."}, 403)
    data = request.get_json() or {}
    note = (data.get("note") or "").strip()
    result, error = cancel_loan_request(
        request_id,
        actor=session.get("username"),
        actor_role=session.get("role"),
        note=note,
    )
    if error:
        return _json({"error": error}, 400)
    return _json(result)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Audit log routes
# ---------------------------------------------------------------------------

@app.route("/api/admin/audit-log", methods=["GET"])
@require_mod_api
def api_audit_log():
    from services import get_audit_log
    username        = request.args.get("username")
    target_username = request.args.get("target_username")
    loan_id         = request.args.get("loan_id")
    action_type     = request.args.get("action_type")
    target_type     = request.args.get("target_type")
    target_id       = request.args.get("target_id")
    date_from       = request.args.get("date_from")
    date_to         = request.args.get("date_to")
    limit           = min(int(request.args.get("limit", 50)), 200)
    offset          = int(request.args.get("offset", 0))
    rows, total, error = get_audit_log(
        username=username, action_type=action_type,
        target_type=target_type, target_id=target_id,
        date_from=date_from, date_to=date_to,
        limit=limit, offset=offset,
        target_username=target_username, loan_id=loan_id)
    if error:
        return _json({"error": error}, 500)
    return _json({"rows": rows, "total": total, "limit": limit, "offset": offset})


@app.route("/dashboard/admin/audit-log")
@role_required("mod", "admin")
def audit_log_page():
    return render_template("audit_log.html",
                           username=session.get("username"),
                           role=session.get("role"))


# ---------------------------------------------------------------------------
# Loan event timeline routes
# ---------------------------------------------------------------------------

@app.route("/api/loans/<loan_id>/events", methods=["GET"])
@require_auth
def api_loan_events(loan_id):
    from services import get_loan_events
    events, error = get_loan_events(loan_id)
    if error:
        return _json({"error": error}, 500)
    return _json(events)


@app.route("/api/loans/<loan_id>/events", methods=["POST"])
@require_mod_api
def api_add_loan_event(loan_id):
    from services import add_loan_event, log_audit
    data    = request.get_json() or {}
    etype   = (data.get("event_type") or "").strip()
    details = (data.get("details") or "").strip()
    actor   = session.get("username", "system")
    if not etype:
        return _json({"error": "event_type required"}, 400)
    add_loan_event(loan_id, etype, actor, details or None)
    log_audit(actor, session.get("role","mod"), "loan_event_added",
              "loan", loan_id, new_value={"event_type": etype, "details": details})
    return _json({"ok": True})


# ---------------------------------------------------------------------------
# Notification routes
# ---------------------------------------------------------------------------

@app.route("/api/notifications", methods=["GET"])
@login_required
def api_get_notifications():
    from services import get_notifications
    unread_only = request.args.get("unread") == "1"
    limit  = min(int(request.args.get("limit", 50)), 100)
    offset = int(request.args.get("offset", 0))
    notifs, unread_count, total, error = get_notifications(
        session["username"], unread_only=unread_only, limit=limit, offset=offset)
    if error:
        return _json({"error": error}, 500)
    return _json({"notifications": notifs, "unread_count": unread_count,
                  "total": total, "limit": limit, "offset": offset})


@app.route("/api/admin/notifications/purge", methods=["POST"])
@require_admin_api
def api_purge_notifications():
    from services import purge_old_notifications
    data = request.get_json() or {}
    days = int(data.get("days", 90))
    if days < 7:
        return _json({"error": "Minimum retention is 7 days."}, 400)
    deleted, error = purge_old_notifications(days=days)
    if error:
        return _json({"error": error}, 500)
    return _json({"ok": True, "deleted": deleted, "days": days})


@app.route("/api/notifications/read", methods=["POST"])
@login_required
def api_mark_notifications_read():
    from services import mark_notifications_read
    data = request.get_json() or {}
    ids  = data.get("ids")  # list of ints or None = mark all
    ok, error = mark_notifications_read(session["username"], ids)
    if error:
        return _json({"error": error}, 500)
    return _json({"ok": True})


# ---------------------------------------------------------------------------
# Verified lender routes
# ---------------------------------------------------------------------------

@app.route("/api/admin/verified-lender/<username>", methods=["GET"])
@require_mod_api
def api_get_verified_lender(username):
    from services import get_verified_lender_status
    verified, details, error = get_verified_lender_status(username)
    if error:
        return _json({"error": error}, 500)
    return _json(details or {"verified": False})


@app.route("/api/admin/verified-lender/<username>", methods=["POST"])
@require_mod_api
def api_set_verified_lender(username):
    from services import set_verified_lender, log_audit, create_notification
    data     = request.get_json() or {}
    verified = bool(data.get("verified", True))
    note     = (data.get("note") or "").strip() or None
    actor    = session.get("username", "system")
    ok, error = set_verified_lender(username, verified, actor, note)
    if error:
        return _json({"error": error}, 500)
    action = "verified_lender_granted" if verified else "verified_lender_revoked"
    log_audit(actor, session.get("role", "mod"), action,
              "user", username,
              new_value={"verified": verified, "note": note})
    if verified:
        create_notification(
            username, "verification_updated",
            "Lender Verification Approved",
            "You have completed the LoanCentral lender verification process. "
            "You can now access lender features on the dashboard.")
    else:
        create_notification(
            username, "verification_updated",
            "Lender Verification Status Updated",
            "Your lender verification status has been updated by a moderator. "
            "Contact a mod if you have questions.")
    return _json({"ok": True})


# ---------------------------------------------------------------------------
# Global search
# ---------------------------------------------------------------------------

@app.route("/api/admin/search", methods=["GET"])
@require_mod_api
def api_global_search():
    from services import global_search
    query         = request.args.get("q", "").strip()
    search_type   = request.args.get("type", "all")
    status_filter = request.args.get("status")
    limit         = min(int(request.args.get("limit", 50)), 100)
    offset        = int(request.args.get("offset", 0))
    results, total, error = global_search(
        query, search_type=search_type,
        status_filter=status_filter, limit=limit, offset=offset)
    if error:
        return _json({"error": error}, 500)
    return _json({"results": results, "total": total, "query": query})


@app.route("/dashboard/admin/search")
@role_required("mod", "admin")
def global_search_page():
    return render_template("global_search.html",
                           username=session.get("username"),
                           role=session.get("role"))


# ---------------------------------------------------------------------------
# Admin: lender directory + lender profile (Sprint 6)
# ---------------------------------------------------------------------------

@app.route("/api/admin/lenders", methods=["GET"])
@require_admin_api
def api_admin_lenders():
    from services import list_lenders
    verified_filter = request.args.get("verified") or None
    if verified_filter not in (None, "verified", "unverified", "revoked"):
        return _json({"error": "Invalid verified filter."}, 400)
    has_reddit = None
    if request.args.get("has_reddit") == "1":
        has_reddit = True
    elif request.args.get("has_reddit") == "0":
        has_reddit = False
    q      = request.args.get("q", "").strip() or None
    limit  = min(int(request.args.get("limit", 100)), 200)
    offset = int(request.args.get("offset", 0))
    rows, total, error = list_lenders(
        verified_filter=verified_filter, has_reddit=has_reddit,
        q=q, limit=limit, offset=offset)
    if error:
        return _json({"error": error}, 500)
    return _json({"lenders": rows, "total": total, "limit": limit, "offset": offset})


@app.route("/dashboard/admin/lenders")
@admin_required
def admin_lenders_page():
    return render_template("admin_lenders.html",
                           username=session["username"],
                           role=session["role"])


@app.route("/api/admin/lenders/<username>", methods=["GET"])
@require_admin_api
def api_admin_lender_profile(username):
    from services import get_admin_user_profile, get_loan_history
    profile, error = get_admin_user_profile(username)
    if error:
        return _json({"error": error}, 500)
    loans, _ = get_loan_history(username, role="lender", limit=100)
    profile["loans"] = loans or []
    return _json(profile)


@app.route("/dashboard/admin/lenders/<username>")
@admin_required
def admin_lender_profile_page(username):
    return render_template("admin_lender_profile.html",
                           username=session["username"],
                           role=session["role"],
                           lender_username=username.lower())


# ---------------------------------------------------------------------------
# Reddit username linking
# ---------------------------------------------------------------------------

@app.route("/api/admin/users/<username>/reddit-link", methods=["GET"])
@require_mod_api
def api_get_reddit_link(username):
    from services import get_reddit_username
    rname, linked_at, linked_by = get_reddit_username(username)
    return _json({"username": username, "reddit_username": rname,
                  "linked_at": linked_at, "linked_by": linked_by})


@app.route("/api/admin/users/<username>/reddit-link", methods=["POST"])
@require_mod_api
def api_set_reddit_link(username):
    from services import link_reddit_username, log_audit
    data = request.get_json() or {}
    reddit_username = (data.get("reddit_username") or "").strip()
    actor = session.get("username", "api-key")
    ok, err = link_reddit_username(username, reddit_username, actor)
    if not ok:
        return _json({"error": err}, 400)
    log_audit(actor, session.get("role", "mod"), "reddit_username_linked",
              "user", username, new_value={"reddit_username": reddit_username})
    return _json({"ok": True, "username": username, "reddit_username": reddit_username})


@app.route("/api/admin/users/<username>/reddit-link", methods=["DELETE"])
@require_mod_api
def api_delete_reddit_link(username):
    from services import unlink_reddit_username, log_audit
    actor = session.get("username", "api-key")
    ok, err = unlink_reddit_username(username, actor)
    if not ok:
        return _json({"error": err}, 400)
    log_audit(actor, session.get("role", "mod"), "reddit_username_unlinked",
              "user", username)
    return _json({"ok": True})


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

@app.route("/health")
def health_check():
    """Lightweight health endpoint for uptime monitors. Never exposes secrets."""
    db_ok = False
    try:
        from services import _get_db
        conn = _get_db()
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            cur.close()
            conn.close()
            db_ok = True
    except Exception:
        pass
    status = "ok" if db_ok else "degraded"
    return _json({
        "status": status,
        "db": "ok" if db_ok else "error",
        "env": "dev" if IS_DEV else "prod",
        "build": BUILD_ID,
    }, 200 if db_ok else 503)


# ---------------------------------------------------------------------------
# Admin metrics
# ---------------------------------------------------------------------------

@app.route("/api/admin/metrics", methods=["GET"])
@require_admin_api
def api_admin_metrics():
    from services import get_platform_metrics
    metrics, error = get_platform_metrics()
    if error:
        return _json({"error": error}, 500)
    return _json(metrics)


@app.route("/api/admin/metrics/expanded", methods=["GET"])
@require_admin_api
def api_admin_metrics_expanded():
    from services import get_expanded_metrics
    metrics, error = get_expanded_metrics()
    if error:
        return _json({"error": error}, 500)
    return _json(metrics)


# ---------------------------------------------------------------------------
# Feedback — user-facing
# ---------------------------------------------------------------------------

@app.route("/feedback")
@login_required
def feedback_page():
    from services import get_feedback_list, log_analytics_event
    username = session["username"]
    role     = session["role"]
    my_feedback, _, _ = get_feedback_list(username=username, limit=50)
    log_analytics_event(username, "page_view", page="/feedback")
    return render_template("feedback.html", username=username, role=role,
                           my_feedback=my_feedback)


@app.route("/api/feedback", methods=["POST"])
@require_auth
def api_submit_feedback():
    from services import create_feedback, log_analytics_event
    username = session["username"]
    data     = request.get_json(silent=True) or {}
    category    = data.get("category", "").strip()
    title       = data.get("title", "").strip()
    description = data.get("description", "").strip()
    fid, error = create_feedback(username, category, title, description)
    if error:
        return _json({"error": error}, 400)
    log_analytics_event(username, "feedback_submit",
                        metadata={"category": category})
    return _json({"id": fid, "message": "Feedback submitted. Thank you!"}, 201)


@app.route("/api/feedback", methods=["GET"])
@require_auth
def api_my_feedback():
    from services import get_feedback_list
    username = session["username"]
    items, total, error = get_feedback_list(username=username, limit=50)
    if error:
        return _json({"error": error}, 500)
    return _json({"feedback": items, "total": total})


# ---------------------------------------------------------------------------
# Feedback — admin management
# ---------------------------------------------------------------------------

@app.route("/admin/feedback")
@role_required("mod", "admin")
def admin_feedback_page():
    from services import get_feedback_list, log_analytics_event
    username = session["username"]
    role     = session["role"]
    log_analytics_event(username, "page_view", page="/admin/feedback")
    return render_template("admin_feedback.html", username=username, role=role)


@app.route("/api/admin/feedback", methods=["GET"])
@require_mod_api
def api_admin_feedback_list():
    from services import get_feedback_list
    status   = request.args.get("status") or None
    category = request.args.get("category") or None
    limit    = min(int(request.args.get("limit", 100)), 500)
    offset   = int(request.args.get("offset", 0))
    items, total, error = get_feedback_list(status=status, category=category,
                                            limit=limit, offset=offset)
    if error:
        return _json({"error": error}, 500)
    return _json({"feedback": items, "total": total})


@app.route("/api/admin/feedback/<int:feedback_id>", methods=["PATCH"])
@require_mod_api
def api_admin_feedback_update(feedback_id):
    from services import update_feedback_status
    data          = request.get_json(silent=True) or {}
    status        = data.get("status", "").strip()
    reviewer_note = data.get("reviewer_note", "").strip() or None
    reviewer      = session.get("username", "system")
    ok, error = update_feedback_status(feedback_id, status, reviewer, reviewer_note)
    if not ok:
        return _json({"error": error}, 400)
    return _json({"message": "Updated"})


# ---------------------------------------------------------------------------
# Notification preferences
# ---------------------------------------------------------------------------

@app.route("/api/notifications/preferences", methods=["GET"])
@require_auth
def api_get_notif_prefs():
    from services import get_notification_preferences
    prefs, _ = get_notification_preferences(session["username"])
    return _json(prefs)


@app.route("/api/notifications/preferences", methods=["PUT"])
@require_auth
def api_update_notif_prefs():
    from services import update_notification_preferences
    data = request.get_json(silent=True) or {}
    ok, error = update_notification_preferences(
        session["username"],
        bool(data.get("due_date_reminders", True)),
        bool(data.get("status_updates", True)),
        bool(data.get("verification_updates", True)),
        bool(data.get("dispute_updates", True)),
    )
    if not ok:
        return _json({"error": error}, 500)
    return _json({"message": "Preferences saved"})


# ---------------------------------------------------------------------------
# User activity timeline (audit investigations)
# ---------------------------------------------------------------------------

@app.route("/audit/user/<username>")
@login_required
def audit_user_timeline(username):
    if session.get("role") not in ("mod", "admin"):
        return redirect(url_for("dashboard_lender"))
    from services import get_user_activity_timeline, log_analytics_event
    viewer   = session["username"]
    role     = session["role"]
    events, error = get_user_activity_timeline(username, limit=100)
    log_analytics_event(viewer, "page_view", page=f"/audit/user/{username}")
    return render_template("audit_user.html", username=viewer, role=role,
                           target_user=username, events=events, error=error)


@app.route("/api/audit/user/<username>/timeline", methods=["GET"])
@require_mod_api
def api_user_timeline(username):
    from services import get_user_activity_timeline
    limit  = min(int(request.args.get("limit", 100)), 500)
    events, error = get_user_activity_timeline(username, limit=limit)
    if error:
        return _json({"error": error}, 500)
    return _json({"username": username, "events": events, "total": len(events)})


# ---------------------------------------------------------------------------
# Beta analytics
# ---------------------------------------------------------------------------

@app.route("/api/admin/analytics", methods=["GET"])
@require_admin_api
def api_admin_analytics():
    from services import get_analytics_summary
    days = min(int(request.args.get("days", 30)), 365)
    summary, error = get_analytics_summary(days)
    if error:
        return _json({"error": error}, 500)
    return _json(summary)


# =============================================================================
# SPRINT 10 — MOD QUEUE, COMMUNITY HEALTH, LENDER/BORROWER MGMT, ANNOUNCEMENTS
# =============================================================================

# ---------------------------------------------------------------------------
# Moderator work queue
# ---------------------------------------------------------------------------

@app.route("/mod/queue")
@role_required("mod", "admin")
def mod_queue_page():
    from services import log_analytics_event
    log_analytics_event(session["username"], "page_view", page="/mod/queue")
    return render_template("mod_queue.html",
                           username=session["username"], role=session["role"])


@app.route("/api/mod/queue", methods=["GET"])
@require_mod_api
def api_mod_queue():
    from services import get_mod_queue
    queue, error = get_mod_queue()
    if error:
        return _json({"error": error}, 500)
    return _json(queue)


# ---------------------------------------------------------------------------
# Community health dashboard
# ---------------------------------------------------------------------------

@app.route("/admin/health")
@role_required("mod", "admin")
def community_health_page():
    from services import log_analytics_event
    log_analytics_event(session["username"], "page_view", page="/admin/health")
    return render_template("community_health.html",
                           username=session["username"], role=session["role"])


@app.route("/api/admin/health", methods=["GET"])
@require_mod_api
def api_community_health():
    from services import get_community_health
    try:
        period = int(request.args.get("period", 30))
    except (TypeError, ValueError):
        period = 30
    period = period if period in (7, 30, 90) else 30
    health, error = get_community_health(period)
    if error:
        return _json({"error": error}, 500)
    return _json(health)


# ---------------------------------------------------------------------------
# Lender management
# ---------------------------------------------------------------------------

@app.route("/admin/lenders/management")
@role_required("mod", "admin")
def lender_management_page():
    from services import log_analytics_event
    log_analytics_event(session["username"], "page_view", page="/admin/lenders/management")
    return render_template("lender_management.html",
                           username=session["username"], role=session["role"])


@app.route("/api/admin/lenders/management", methods=["GET"])
@require_mod_api
def api_lender_management():
    from services import get_lender_management_list
    q        = request.args.get("q", "").strip() or None
    verified = request.args.get("verified") or None
    limit    = min(int(request.args.get("limit", 100)), 500)
    offset   = int(request.args.get("offset", 0))
    items, total, error = get_lender_management_list(
        q=q, verified_filter=verified, limit=limit, offset=offset)
    if error:
        return _json({"error": error}, 500)
    return _json({"lenders": items, "total": total})


# ---------------------------------------------------------------------------
# Borrower activity dashboard
# ---------------------------------------------------------------------------

@app.route("/admin/borrowers")
@role_required("mod", "admin")
def borrower_activity_page():
    from services import log_analytics_event
    log_analytics_event(session["username"], "page_view", page="/admin/borrowers")
    return render_template("admin_borrowers.html",
                           username=session["username"], role=session["role"])


@app.route("/api/admin/borrowers", methods=["GET"])
@require_mod_api
def api_borrower_activity():
    from services import get_borrower_activity_list
    q            = request.args.get("q", "").strip() or None
    has_disputes = request.args.get("disputes") == "1"
    limit        = min(int(request.args.get("limit", 100)), 500)
    offset       = int(request.args.get("offset", 0))
    items, total, error = get_borrower_activity_list(
        q=q, has_disputes=has_disputes, limit=limit, offset=offset)
    if error:
        return _json({"error": error}, 500)
    return _json({"borrowers": items, "total": total})


# ---------------------------------------------------------------------------
# Announcements
# ---------------------------------------------------------------------------

@app.route("/api/announcements", methods=["GET"])
def api_get_announcements():
    from services import get_announcements
    items, error = get_announcements(active_only=True)
    if error:
        return _json({"error": error}, 500)
    return _json({"announcements": items})


@app.route("/api/admin/announcements", methods=["GET"])
@require_mod_api
def api_admin_get_announcements():
    from services import get_announcements
    active_only = request.args.get("active_only", "0") != "0"
    items, error = get_announcements(active_only=active_only, limit=100)
    if error:
        return _json({"error": error}, 500)
    return _json({"announcements": items})


@app.route("/api/admin/announcements", methods=["POST"])
@require_mod_api
def api_create_announcement():
    from services import create_announcement
    data    = request.get_json(silent=True) or {}
    title   = data.get("title", "").strip()
    body    = data.get("body", "").strip()
    pinned  = bool(data.get("pinned", False))
    expires = data.get("expires_at") or None
    author  = session.get("username", "system")
    aid, error = create_announcement(title, body, author, pinned, expires)
    if error:
        return _json({"error": error}, 400)
    return _json({"id": aid, "message": "Announcement posted"}, 201)


@app.route("/api/admin/announcements/<int:announcement_id>", methods=["DELETE"])
@require_mod_api
def api_delete_announcement(announcement_id):
    from services import deactivate_announcement
    actor = session.get("username", "system")
    ok, error = deactivate_announcement(announcement_id, actor)
    if not ok:
        return _json({"error": error}, 400)
    return _json({"message": "Announcement deactivated"})


# ---------------------------------------------------------------------------
# Audit investigation summary
# ---------------------------------------------------------------------------

@app.route("/api/audit/user/<username>/summary", methods=["GET"])
@require_mod_api
def api_audit_investigation_summary(username):
    from services import get_audit_investigation_summary
    summary, error = get_audit_investigation_summary(username)
    if error:
        return _json({"error": error}, 500)
    return _json(summary)


# ---------------------------------------------------------------------------
# Admin Command Center
# ---------------------------------------------------------------------------

@app.route("/admin")
@role_required("mod", "admin")
def admin_hub():
    from services import log_analytics_event
    log_analytics_event(session["username"], "page_view", page="/admin")
    return render_template("admin_hub.html",
                           username=session["username"],
                           role=session["role"])


# ---------------------------------------------------------------------------
# Moderator Investigation Center
# ---------------------------------------------------------------------------

@app.route("/dashboard/mod/investigation/<username>")
@role_required("mod", "admin")
def mod_investigation(username):
    from services import log_analytics_event
    log_analytics_event(session["username"], "page_view",
                        page=f"/dashboard/mod/investigation/{username}")
    return render_template("mod_investigation.html",
                           username=session["username"],
                           role=session["role"],
                           target_user=username.lower())


# ---------------------------------------------------------------------------
# Moderator Disputes Center
# ---------------------------------------------------------------------------

@app.route("/dashboard/mod/disputes")
@role_required("mod", "admin")
def mod_disputes_page():
    from services import log_analytics_event
    log_analytics_event(session["username"], "page_view", page="/dashboard/mod/disputes")
    return render_template("mod_disputes.html",
                           username=session["username"],
                           role=session["role"])


@app.route("/api/mod/disputes", methods=["GET"])
@require_mod_api
def api_mod_disputes():
    from services import get_disputed_loans
    loans, error = get_disputed_loans(limit=200)
    if error:
        return _json({"error": error}, 500)
    return _json({"disputes": loans, "total": len(loans)})


# ---------------------------------------------------------------------------
# Moderator Notes
# ---------------------------------------------------------------------------

@app.route("/api/mod/notes/<username>", methods=["GET"])
@require_mod_api
def api_get_mod_notes(username):
    from services import get_mod_notes
    include_archived = request.args.get("archived") == "1"
    notes, error = get_mod_notes(username, include_archived=include_archived)
    if error:
        return _json({"error": error}, 500)
    return _json({"notes": notes, "total": len(notes)})


@app.route("/api/mod/notes/<username>", methods=["POST"])
@require_mod_api
def api_create_mod_note(username):
    from services import create_mod_note, log_audit
    data     = request.get_json(silent=True) or {}
    category = (data.get("category") or "general").strip()
    content  = (data.get("content") or "").strip()
    author   = session.get("username", "system")
    note_id, error = create_mod_note(username, author, category, content)
    if error:
        return _json({"error": error}, 400)
    log_audit(author, session.get("role", "mod"), "mod_note_created",
              "user", username, new_value={"category": category, "note_id": note_id})
    return _json({"id": note_id, "message": "Note saved"}, 201)


@app.route("/api/mod/notes/<int:note_id>", methods=["PATCH"])
@require_mod_api
def api_update_mod_note(note_id):
    from services import update_mod_note, log_audit
    data    = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    editor  = session.get("username", "system")
    ok, error = update_mod_note(note_id, content, editor)
    if not ok:
        return _json({"error": error}, 400)
    log_audit(editor, session.get("role", "mod"), "mod_note_updated",
              "note", str(note_id))
    return _json({"message": "Note updated"})


@app.route("/api/mod/notes/<int:note_id>", methods=["DELETE"])
@require_mod_api
def api_archive_mod_note(note_id):
    from services import archive_mod_note, log_audit
    actor = session.get("username", "system")
    ok, error = archive_mod_note(note_id, actor)
    if not ok:
        return _json({"error": error}, 400)
    log_audit(actor, session.get("role", "mod"), "mod_note_archived",
              "note", str(note_id))
    return _json({"message": "Note archived"})


# ---------------------------------------------------------------------------
# Risk Review Dashboard
# ---------------------------------------------------------------------------

@app.route("/dashboard/mod/risk")
@role_required("mod", "admin")
def mod_risk_page():
    from services import log_analytics_event
    log_analytics_event(session["username"], "page_view", page="/dashboard/mod/risk")
    return render_template("mod_risk.html",
                           username=session["username"],
                           role=session["role"])


@app.route("/api/mod/risk", methods=["GET"])
@require_mod_api
def api_mod_risk():
    from services import get_risk_indicators
    indicators, error = get_risk_indicators(limit=100)
    if error:
        return _json({"error": error}, 500)
    return _json({"indicators": indicators, "total": len(indicators)})


# ---------------------------------------------------------------------------
# Communication Sprint — notification queue admin routes
# ---------------------------------------------------------------------------

@app.route("/admin/communications")
@role_required("admin")
def admin_communications_page():
    from services import log_analytics_event
    log_analytics_event(session["username"], "page_view", page="/admin/communications")
    return render_template("admin_communications.html",
                           username=session["username"], role=session["role"])


@app.route("/api/admin/notifications/queue", methods=["GET"])
@require_admin_api
def api_notification_queue():
    from services import get_notification_queue
    status    = request.args.get("status")
    channel   = request.args.get("channel")
    recipient = request.args.get("recipient")
    limit     = min(int(request.args.get("limit",  100)), 500)
    offset    = int(request.args.get("offset", 0))
    rows, total, error = get_notification_queue(
        status=status, channel=channel, recipient=recipient,
        limit=limit, offset=offset)
    if error:
        return _json({"error": error}, 500)
    return _json({"queue": rows, "total": total, "limit": limit, "offset": offset})


@app.route("/api/admin/notifications/queue/stats", methods=["GET"])
@require_admin_api
def api_notification_queue_stats():
    from services import get_queue_stats
    stats, error = get_queue_stats()
    if error:
        return _json({"error": error}, 500)
    return _json(stats)


@app.route("/api/admin/notifications/queue/reminders", methods=["POST"])
@require_admin_api
def api_trigger_due_reminders():
    from services import queue_due_reminders, log_audit
    dry_run = request.json.get("dry_run", False) if request.json else False
    queued, skipped, error = queue_due_reminders(dry_run=dry_run)
    if error:
        return _json({"error": error}, 500)
    log_audit(session["username"], session.get("role", "admin"), "trigger_due_reminders",
              new_value={"dry_run": dry_run, "queued": queued, "skipped": skipped})
    return _json({"queued": queued, "skipped": skipped, "dry_run": dry_run})


# ---------------------------------------------------------------------------
# Loan Request Sprint
# ---------------------------------------------------------------------------

@app.route("/dashboard/borrower/requests")
@role_required("borrower", "lender", "mod", "admin")
def borrower_requests_page():
    return render_template("borrower_requests.html",
                           username=session["username"], role=session["role"])


@app.route("/dashboard/mod/requests")
@role_required("mod", "admin")
def mod_request_queue_page():
    return render_template("mod_request_queue.html",
                           username=session["username"], role=session["role"])


@app.route("/dashboard/requests/<request_id>")
@role_required("borrower", "lender", "mod", "admin")
def request_detail_page(request_id):
    from services import get_loan_request
    req, error = get_loan_request(request_id)
    if error or not req:
        return render_template("error.html", code=404, message="Request not found."), 404
    # Borrowers may only view their own requests
    if session["role"] not in ("mod", "admin"):
        if req["borrower_username"].lower() != session["username"].lower():
            return render_template("error.html", code=403,
                                   message="You can only view your own requests."), 403
    return render_template("request_detail.html",
                           req=req,
                           request_id=request_id,
                           viewer_role=session["role"],
                           username=session["username"],
                           role=session["role"])


# ---- Loan Request API -------------------------------------------------------

@app.route("/api/loan-requests", methods=["POST"])
@require_auth
def api_create_loan_request():
    from services import create_loan_request
    data = request.json or {}
    borrower = (data.get("borrower_username") or session.get("username", "")).strip().lower()
    if not borrower:
        return _json({"error": "borrower_username required"}, 400)
    # Non-mod/admin users can only create requests for themselves
    if session.get("role") not in ("mod", "admin"):
        if borrower != session.get("username", "").lower():
            return _json({"error": "You may only create requests for yourself."}, 403)
    request_id, error = create_loan_request(
        borrower_username=borrower,
        reddit_username=data.get("reddit_username"),
        thread_url=data.get("thread_url"),
        reddit_post_id=data.get("reddit_post_id"),
        reddit_comment_id=data.get("reddit_comment_id"),
        requested_amount=data.get("requested_amount"),
        requested_repayment_amount=data.get("requested_repayment_amount"),
        requested_due_date=data.get("requested_due_date"),
        notes=data.get("notes"),
    )
    if error:
        return _json({"error": error}, 500)
    from services import log_request_event, find_duplicate_loan_requests, create_notification
    log_request_event(request_id, "created", actor=session.get("username"),
                      note=f"Request created for u/{borrower}")
    dupes, _ = find_duplicate_loan_requests(borrower, days=10, exclude_request_id=request_id)
    create_notification(
        borrower, "request_recorded",
        "Loan request recorded",
        f"Your loan request {request_id} has been recorded."
    )
    if len(dupes) > 0:
        from services import _notify_all_mods
        _notify_all_mods(
            "duplicate_request_flagged",
            "Possible duplicate request",
            f"Borrower u/{borrower} submitted request {request_id} — a possible duplicate exists.",
        )
    return _json({"request_id": request_id, "possible_duplicate": len(dupes) > 0}, 201)


@app.route("/api/loan-requests", methods=["GET"])
@require_mod_api
def api_list_loan_requests():
    from services import get_loan_request_queue
    status    = request.args.get("status")
    borrower  = request.args.get("borrower")
    date_from = request.args.get("date_from")
    date_to   = request.args.get("date_to")
    amount_min = request.args.get("amount_min", type=float)
    amount_max = request.args.get("amount_max", type=float)
    limit  = min(int(request.args.get("limit",  200)), 500)
    offset = int(request.args.get("offset", 0))
    rows, total, error = get_loan_request_queue(
        status=status, borrower=borrower,
        date_from=date_from, date_to=date_to,
        amount_min=amount_min, amount_max=amount_max,
        limit=limit, offset=offset)
    if error:
        return _json({"error": error}, 500)
    return _json({"requests": rows, "total": total, "limit": limit, "offset": offset})


@app.route("/api/loan-requests/mine", methods=["GET"])
@require_auth
def api_my_loan_requests():
    from services import get_loan_requests_for_borrower
    limit  = min(int(request.args.get("limit", 100)), 500)
    offset = int(request.args.get("offset", 0))
    rows, total, error = get_loan_requests_for_borrower(
        session["username"], limit=limit, offset=offset)
    if error:
        return _json({"error": error}, 500)
    return _json({"requests": rows, "total": total})


@app.route("/api/loan-requests/<request_id>", methods=["GET"])
@require_auth
def api_get_loan_request(request_id):
    from services import get_loan_request
    req, error = get_loan_request(request_id)
    if error == "Request not found":
        return _json({"error": "Not found"}, 404)
    if error:
        return _json({"error": error}, 500)
    if session.get("role") not in ("mod", "admin"):
        if req["borrower_username"].lower() != session.get("username", "").lower():
            return _json({"error": "Forbidden"}, 403)
    return _json(req)


@app.route("/api/loan-requests/<request_id>/status", methods=["PATCH"])
@require_mod_api
def api_update_request_status(request_id):
    from services import update_request_status, log_audit
    data       = request.json or {}
    new_status = (data.get("status") or "").strip()
    note       = data.get("note", "")
    if not new_status:
        return _json({"error": "status required"}, 400)
    ok, error = update_request_status(request_id, new_status, session["username"], note)
    if not ok:
        return _json({"error": error}, 400 if "Invalid" in error or "not found" in error.lower() else 500)
    log_audit(session["username"], session.get("role","mod"), "request_status_updated",
              target_type="loan_request", target_id=request_id,
              new_value={"status": new_status, "note": note})
    from services import log_request_event, get_loan_request, create_notification
    log_request_event(request_id, "status_changed", actor=session["username"],
                      note=f"Status → {new_status}" + (f": {note}" if note else ""))
    req, _ = get_loan_request(request_id)
    if req:
        borrower = req.get("borrower_username", "")
        if new_status == "funded":
            create_notification(
                borrower, "request_funded",
                "Request marked as funded",
                f"Your loan request {request_id} has been marked as funded."
            )
        elif new_status == "expired":
            create_notification(
                borrower, "request_expired",
                "Request expired",
                f"Your loan request {request_id} has expired."
            )
        elif new_status == "removed":
            create_notification(
                borrower, "request_removed",
                "Request removed",
                f"Your loan request {request_id} has been removed by a moderator."
            )
    return _json({"ok": True, "request_id": request_id, "status": new_status})


@app.route("/api/loan-requests/<request_id>/link", methods=["POST"])
@require_mod_api
def api_link_request_to_loan(request_id):
    from services import link_request_to_loan, log_audit
    data        = request.json or {}
    loan_db_id  = data.get("loan_db_id")
    override    = bool(data.get("override", False))
    if not loan_db_id:
        return _json({"error": "loan_db_id required"}, 400)
    ok, error = link_request_to_loan(request_id, int(loan_db_id),
                                     session["username"], override=override)
    if not ok:
        return _json({"error": error}, 409 if "already linked" in error else 400)
    log_audit(session["username"], session.get("role","mod"), "request_linked_to_loan",
              target_type="loan_request", target_id=request_id,
              new_value={"loan_db_id": loan_db_id, "override": override})
    from services import log_request_event
    log_request_event(request_id, "linked_to_loan", actor=session["username"],
                      note=f"Linked to loan DB ID {loan_db_id}" + (" (override)" if override else ""))
    return _json({"ok": True, "request_id": request_id, "loan_db_id": loan_db_id})


@app.route("/api/admin/request-analytics", methods=["GET"])
@require_admin_api
def api_request_analytics():
    from services import get_request_analytics
    stats, error = get_request_analytics()
    if error:
        return _json({"error": error}, 500)
    return _json(stats)


@app.route("/api/admin/requests/expire", methods=["POST"])
@require_admin_api
def api_expire_requests():
    from services import expire_old_requests, log_audit
    data    = request.json or {}
    days    = int(data.get("days", 10))
    dry_run = bool(data.get("dry_run", False))
    expired, error = expire_old_requests(days=days, dry_run=dry_run)
    if error:
        return _json({"error": error}, 500)
    if not dry_run:
        log_audit(session["username"], session.get("role","admin"), "requests_expired",
                  new_value={"expired": expired, "days": days})
    return _json({"expired": expired, "days": days, "dry_run": dry_run})


@app.route("/api/loan-requests/search", methods=["GET"])
@require_mod_api
def api_search_loan_requests():
    from services import search_loan_requests
    q          = request.args.get("q", "").strip()
    status     = request.args.get("status")
    amount_min = request.args.get("amount_min", type=float)
    amount_max = request.args.get("amount_max", type=float)
    limit      = min(int(request.args.get("limit", 50)), 200)
    offset     = int(request.args.get("offset", 0))
    results, total, error = search_loan_requests(
        q=q, status=status,
        amount_min=amount_min, amount_max=amount_max,
        limit=limit, offset=offset)
    if error:
        return _json({"error": error}, 500)
    return _json({"results": results, "total": total})


@app.route("/api/loan-requests/<request_id>/events", methods=["GET"])
@require_auth
def api_get_request_events(request_id):
    from services import get_loan_request, get_request_events
    # Ownership check for non-mods
    if session.get("role") not in ("mod", "admin"):
        req, err = get_loan_request(request_id)
        if err or not req:
            return _json({"error": "Not found"}, 404)
        if req["borrower_username"].lower() != session.get("username", "").lower():
            return _json({"error": "Forbidden"}, 403)
    events, error = get_request_events(request_id)
    if error:
        return _json({"error": error}, 500)
    return _json({"events": events, "request_id": request_id})


@app.route("/api/loan-requests/<request_id>/duplicates", methods=["GET"])
@require_mod_api
def api_get_request_duplicates(request_id):
    from services import get_loan_request, find_duplicate_loan_requests
    req, err = get_loan_request(request_id)
    if err or not req:
        return _json({"error": "Not found"}, 404)
    dupes, error = find_duplicate_loan_requests(
        req["borrower_username"], days=10, exclude_request_id=request_id)
    if error:
        return _json({"error": error}, 500)
    return _json({"duplicates": dupes, "borrower": req["borrower_username"]})


@app.route("/admin/request-analytics")
@role_required("admin")
def admin_request_analytics_page():
    return render_template("admin_request_analytics.html",
                           username=session["username"], role=session["role"])


# ---- Request Review Dashboard -----------------------------------------------

@app.route("/dashboard/mod/request-review")
@role_required("mod", "admin")
def mod_request_review_page():
    return render_template("mod_request_review.html",
                           username=session["username"], role=session["role"])


# ---- Admin Automation Helpers -----------------------------------------------

@app.route("/api/admin/requests/flag-duplicates", methods=["POST"])
@require_admin_api
def api_flag_duplicate_requests():
    from services import flag_possible_duplicates, log_audit
    data    = request.json or {}
    dry_run = bool(data.get("dry_run", False))
    flagged, error = flag_possible_duplicates(dry_run=dry_run)
    if error:
        return _json({"error": error}, 500)
    if not dry_run and flagged:
        log_audit(session["username"], session.get("role", "admin"),
                  "requests_duplicate_flagged",
                  new_value={"flagged_count": len(flagged), "request_ids": flagged})
    return _json({"flagged": flagged, "count": len(flagged), "dry_run": dry_run})


@app.route("/api/admin/requests/missing-threads", methods=["GET"])
@require_admin_api
def api_requests_missing_threads():
    from services import flag_missing_thread_links
    status = request.args.get("status", "open")
    rows, error = flag_missing_thread_links(status_filter=status)
    if error:
        return _json({"error": error}, 500)
    return _json({"requests": rows, "total": len(rows)})


@app.route("/api/admin/requests/unlinked-funded", methods=["GET"])
@require_admin_api
def api_requests_unlinked_funded():
    from services import flag_unlinked_funded_requests
    rows, error = flag_unlinked_funded_requests()
    if error:
        return _json({"error": error}, 500)
    return _json({"requests": rows, "total": len(rows)})


@app.route("/api/admin/requests/quality-report", methods=["GET"])
@require_admin_api
def api_request_quality_report():
    from services import generate_request_quality_report
    report, error = generate_request_quality_report()
    if error:
        return _json({"error": error}, 500)
    return _json(report)


@app.route("/api/admin/requests/backfill", methods=["POST"])
@require_admin_api
def api_backfill_requests():
    from services import backfill_requests_from_loans, log_audit
    data    = request.json or {}
    dry_run = bool(data.get("dry_run", False))
    created, skipped, error = backfill_requests_from_loans(dry_run=dry_run)
    if error:
        return _json({"error": error}, 500)
    if not dry_run and created:
        log_audit(session["username"], session.get("role", "admin"),
                  "requests_backfilled",
                  new_value={"created": created, "skipped": skipped})
    return _json({"created": created, "skipped": skipped, "dry_run": dry_run})


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return _json({"error": "Not found"}, 404)
    return render_template("error.html", code=404, message="Page not found."), 404


@app.errorhandler(403)
def forbidden(e):
    if request.path.startswith("/api/"):
        return _json({"error": "Forbidden"}, 403)
    return render_template("error.html", code=403, message="You don't have permission to view this page."), 403


@app.errorhandler(500)
def server_error(e):
    log_request_error(e)
    if request.path.startswith("/api/"):
        return _json({"error": "Internal server error"}, 500)
    return render_template("error.html", code=500, message="Something went wrong on our end. Try again in a moment."), 500


@app.errorhandler(Exception)
def unhandled_exception(e):
    log_request_error(e, extra="unhandled")
    if request.path.startswith("/api/"):
        return _json({"error": "Internal server error"}, 500)
    return render_template("error.html", code=500, message="Something went wrong on our end. Try again in a moment."), 500


if __name__ == "__main__":
    port  = int(os.getenv("API_PORT", 5000))
    debug = IS_DEV
    app.run(host="0.0.0.0", port=port, debug=debug)
