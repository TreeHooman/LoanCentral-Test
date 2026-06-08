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

API_KEY = os.getenv("API_KEY", "changeme")
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
# Helpers
# ---------------------------------------------------------------------------

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
            conditions.append("(lender ILIKE %s OR borrower ILIKE %s)")
            params += [f"%{search}%", f"%{search}%"]
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
        key = request.headers.get("X-API-Key") or request.args.get("api_key")
        if key == API_KEY:
            return f(*args, **kwargs)
        if session.get("username"):
            return f(*args, **kwargs)
        return _json({"error": "Unauthorized. Provide X-API-Key header or log in."}, 401)
    return decorated


def require_mod_api(f):
    """API endpoints that mods/admins can call."""
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-API-Key") or request.args.get("api_key")
        if key == API_KEY:
            return f(*args, **kwargs)
        if _is_mod_or_admin():
            return f(*args, **kwargs)
        return _json({"error": "Mod access required."}, 403)
    return decorated


def require_admin_api(f):
    """API endpoints that only owner/admin can call."""
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-API-Key") or request.args.get("api_key")
        if key == API_KEY:
            return f(*args, **kwargs)
        if _is_admin():
            return f(*args, **kwargs)
        return _json({"error": "Admin access required."}, 403)
    return decorated


def _can_view_user_profile(target_username):
    key = request.headers.get("X-API-Key") or request.args.get("api_key")
    if key == API_KEY:
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
@role_required("lender", "mod", "admin")
def dashboard_lender():
    return render_template("dashboard_lender.html",
                           username=session["username"],
                           role=session["role"])


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
    result, err = set_user_role(username, role)
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
    try:
        cur = conn.cursor()
        cur.execute("SELECT username, role, subscription_status, last_login FROM user_roles ORDER BY role, username")
        rows = cur.fetchall()
        return _json([
            {"username": r[0], "role": r[1], "subscription_status": r[2], "last_login": r[3]}
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

    if lender:
        loans, error = get_loan_history(lender, role="lender", limit=limit)
        if not error and status:
            loans = [l for l in loans if l["status"] == status]
    elif borrower:
        loans, error = get_loan_history(borrower, role="borrower", limit=limit)
        if not error and status:
            loans = [l for l in loans if l["status"] == status]
    else:
        loans, error = _get_all_loans_from_db(status=status, search=search, limit=limit)

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
        "repay_date", "payment_method", "borrower_acknowledged_at",
        "borrower_acknowledged_note", "thread", "notes"
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
    if not all([lender, amount, currency]):
        return _json({"error": "lender, amount, and currency are required"}, 400)
    result, error = mark_repaid(loan_id, Decimal(str(amount)), currency, lender, actor_role="lender")
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


if __name__ == "__main__":
    port  = int(os.getenv("API_PORT", 5000))
    debug = IS_DEV
    app.run(host="0.0.0.0", port=port, debug=debug)
