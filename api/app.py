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
import time as _time
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

# Secure session cookies
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"]   = not IS_DEV  # HTTPS only in prod

# Simple in-memory per-IP rate limiter for API endpoints (120 req/min)
_api_rl: dict = {}
_API_WINDOW   = 60
_API_LIMIT    = 120


@app.before_request
def _rate_limit_api():
    if not request.path.startswith("/api/"):
        return
    ip  = request.headers.get("X-Forwarded-For", request.remote_addr) or "unknown"
    now = _time.time()
    bucket = _api_rl.setdefault(ip, [])
    # Evict expired entries
    while bucket and now - bucket[0] > _API_WINDOW:
        bucket.pop(0)
    if len(bucket) >= _API_LIMIT:
        return _json({"error": "Rate limit exceeded. Please slow down."}, 429)
    bucket.append(now)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _get_all_loans_from_db(status=None, search=None, limit=50, offset=0,
                           date_from=None, date_to=None,
                           amount_min=None, amount_max=None):
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
            conditions.append("(lender ILIKE %s OR borrower ILIKE %s OR loan_id ILIKE %s OR id::text = %s)")
            params += [f"%{search}%", f"%{search}%", f"%{search}%", search]
        if date_from:
            conditions.append("date_created >= %s")
            params.append(date_from)
        if date_to:
            conditions.append("date_created <= %s")
            params.append(date_to)
        if amount_min is not None:
            conditions.append("amount >= %s")
            params.append(amount_min)
        if amount_max is not None:
            conditions.append("amount <= %s")
            params.append(amount_max)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params += [limit, offset]
        cur.execute(f"""
            SELECT id, loan_id, lender, borrower, amount, amount_repaid,
                   currency, status, date_created, original_thread, date_repaid, notes, due_date
            FROM loans {where}
            ORDER BY date_created DESC LIMIT %s OFFSET %s
        """, params)
        rows = cur.fetchall()
        return [
            {
                "db_id": r[0], "loan_id": r[1], "lender": r[2], "borrower": r[3],
                "amount": r[4], "amount_repaid": r[5], "currency": r[6],
                "status": r[7], "date_created": r[8], "original_thread": r[9],
                "date_repaid": r[10], "notes": r[11], "due_date": r[12],
                "remaining": Decimal(str(r[4])) - Decimal(str(r[5])),
                "repaid_pct": round(float(r[5]) / float(r[4]) * 100, 1) if float(r[4]) > 0 else 0,
            }
            for r in rows
        ], None
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
    """API endpoints that only mods can call."""
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-API-Key") or request.args.get("api_key")
        if key == API_KEY:
            return f(*args, **kwargs)
        if session.get("role") == "mod":
            return f(*args, **kwargs)
        return _json({"error": "Mod access required."}, 403)
    return decorated


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    if not session.get("username"):
        return redirect(url_for("login"))
    role = session.get("role", "borrower")
    if role == "mod":
        return redirect(url_for("dashboard_mod"))
    elif role == "lender":
        return redirect(url_for("dashboard_lender"))
    return redirect(url_for("dashboard_borrower"))


@app.route("/login")
def login():
    if session.get("username"):
        return redirect(url_for("home"))
    from auth import oauth_configured
    return render_template("login.html", oauth_ready=oauth_configured(), is_dev=IS_DEV)


@app.route("/auth/reddit")
def auth_reddit():
    from auth import check_rate_limit, get_auth_url, oauth_configured
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
    from auth import exchange_code
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

    return redirect(url_for("home"))


@app.route("/auth/dev-login", methods=["GET", "POST"])
def auth_dev_login():
    """Dev-only login bypass — disabled in production."""
    if not IS_DEV:
        return redirect(url_for("login"))
    if request.method == "POST":
        from services import get_user_role, update_last_login
        username = request.form.get("username", "").strip().lower()
        if username:
            role, _ = get_user_role(username)
            update_last_login(username)
            session.permanent = True
            session["username"] = username
            session["role"]     = role
            return redirect(url_for("home"))
    return render_template("dev_login.html")


@app.route("/auth/login", methods=["POST"])
def auth_password_login():
    from services import verify_password, update_last_login
    username = request.form.get("username", "").strip().lower()
    password = request.form.get("password", "")
    if not username or not password:
        flash("Username and password are required.", "error")
        return redirect(url_for("login"))
    role, error = verify_password(username, password)
    if error:
        flash(error, "error")
        return redirect(url_for("login"))
    update_last_login(username)
    session.permanent = True
    session["username"] = username
    session["role"]     = role
    return redirect(url_for("home"))


@app.route("/auth/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    from services import verify_password, set_password
    if request.method == "POST":
        current  = request.form.get("current_password", "")
        new_pw   = request.form.get("new_password", "")
        confirm  = request.form.get("confirm_password", "")
        if len(new_pw) < 8:
            flash("Password must be at least 8 characters.", "error")
            return redirect(url_for("change_password"))
        if new_pw != confirm:
            flash("New passwords do not match.", "error")
            return redirect(url_for("change_password"))
        _, error = verify_password(session["username"], current)
        if error:
            flash("Current password is incorrect.", "error")
            return redirect(url_for("change_password"))
        set_password(session["username"], new_pw)
        flash("Password updated successfully.", "success")
        return redirect(url_for("home"))
    return render_template("change_password.html",
                           username=session["username"],
                           role=session["role"])


@app.route("/auth/logout")
def auth_logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard/mod")
@role_required("mod")
def dashboard_mod():
    return render_template("dashboard_mod.html",
                           username=session["username"],
                           role=session["role"])


@app.route("/dashboard/lender")
@role_required("lender", "mod")
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


# ---------------------------------------------------------------------------
# Admin: role management
# ---------------------------------------------------------------------------

@app.route("/api/admin/users/<username>/password", methods=["POST"])
@require_mod_api
def set_user_password(username):
    from services import set_password
    data     = request.get_json() or {}
    password = data.get("password", "")
    if len(password) < 8:
        return _json({"error": "Password must be at least 8 characters."}, 400)
    ok, error = set_password(username.lower(), password)
    if error:
        return _json({"error": error}, 500)
    return _json({"ok": True, "message": f"Password set for u/{username}."})


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
    result, err = set_user_role(username, role, actor=session.get("username", "mod"))
    if err:
        return _json({"error": err}, 400)
    # Fire-and-forget flair sync when granting lender role
    if role == "lender":
        _sync_lender_flair(username)
    return _json({"username": username, "role": role, "ok": True})


def _sync_lender_flair(username: str):
    """Set 'Verified Lender' Reddit flair for a newly promoted lender. Best-effort."""
    try:
        import praw
        reddit = praw.Reddit(
            client_id=os.getenv("REDDIT_CLIENT_ID"),
            client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
            username=os.getenv("REDDIT_USERNAME"),
            password=os.getenv("REDDIT_PASSWORD"),
            user_agent=os.getenv("REDDIT_USER_AGENT",
                                 f"LoanCentral/1.0 by u/{os.getenv('REDDIT_USERNAME', 'LoanBot')}"),
        )
        for sub in [s.strip() for s in os.getenv("SUBREDDITS", "").split(",") if s.strip()]:
            reddit.subreddit(sub).flair.set(username, text="Verified Lender", css_class="lender")
        import logging
        logging.getLogger("LoanCentral").info(f"Flair set for u/{username} → Verified Lender")
    except Exception as e:
        import logging
        logging.getLogger("LoanCentral").error(f"Flair sync failed for u/{username}: {e}")


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

    lender     = request.args.get("lender")
    borrower   = request.args.get("borrower")
    status     = request.args.get("status")
    search     = request.args.get("search")
    limit      = min(int(request.args.get("limit", 50)), 200)
    offset     = max(int(request.args.get("offset", 0)), 0)
    date_from  = request.args.get("date_from") or None
    date_to    = request.args.get("date_to") or None
    amount_min = float(request.args.get("amount_min")) if request.args.get("amount_min") else None
    amount_max = float(request.args.get("amount_max")) if request.args.get("amount_max") else None

    # Non-mods can only see their own data
    if session.get("username") and session.get("role") != "mod":
        me = session["username"]
        if lender and lender.lower() != me:
            return _json({"error": "You can only view your own loans."}, 403)
        if borrower and borrower.lower() != me:
            return _json({"error": "You can only view your own loans."}, 403)

    if lender:
        loans, error = get_loan_history(lender, role="lender", limit=limit, offset=offset, search=search)
        if not error and status:
            loans = [l for l in loans if l["status"] == status]
    elif borrower:
        loans, error = get_loan_history(borrower, role="borrower", limit=limit, offset=offset, search=search)
        if not error and status:
            loans = [l for l in loans if l["status"] == status]
    else:
        loans, error = _get_all_loans_from_db(
            status=status, search=search, limit=limit, offset=offset,
            date_from=date_from, date_to=date_to,
            amount_min=amount_min, amount_max=amount_max,
        )

    if error:
        return _json({"error": error}, 500)

    # Add remaining to any loans missing it
    for loan in loans:
        if "remaining" not in loan:
            loan["remaining"] = float(loan["amount"]) - float(loan["amount_repaid"])

    return _json(loans)


@app.route("/api/loans/<loan_id>", methods=["GET"])
@require_auth
def get_loan(loan_id):
    from services import _get_db
    conn = _get_db()
    if not conn:
        return _json({"error": "Database connection failed"}, 500)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, loan_id, lender, borrower, amount, amount_repaid,
                   currency, status, date_created, original_thread
            FROM loans WHERE id::text = %s OR loan_id = %s
            ORDER BY id DESC LIMIT 1
        """, (loan_id, loan_id))
        row = cur.fetchone()
        if not row:
            return _json({"error": "Loan not found"}, 404)
        loan = {
            "db_id": row[0], "loan_id": row[1], "lender": row[2], "borrower": row[3],
            "amount": row[4], "amount_repaid": row[5], "currency": row[6],
            "status": row[7], "date_created": row[8], "original_thread": row[9],
            "remaining": Decimal(str(row[4])) - Decimal(str(row[5])),
        }
        # Scope check
        if session.get("username") and session.get("role") != "mod":
            me = session["username"]
            if loan["lender"] != me and loan["borrower"] != me:
                return _json({"error": "You can only view your own loans."}, 403)
        return _json(loan)
    finally:
        cur.close()
        conn.close()


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
    from services import get_user_profile, get_loan_history, _get_db
    # Scope check
    if session.get("username") and session.get("role") != "mod":
        if username.lower() != session["username"]:
            return _json({"error": "You can only view your own profile."}, 403)
    profile, error = get_user_profile(username)
    if error:
        return _json({"error": error}, 500)
    loans, _ = get_loan_history(username, role="both", limit=50)
    profile["recent_loans"] = loans or []
    from services import calculate_health_score, credit_tier
    score, _ = calculate_health_score(profile)
    profile["health_score"] = score
    profile["credit_tier"]  = credit_tier(score)
    # Include phone number for own profile
    if session.get("username", "").lower() == username.lower() or session.get("role") == "mod":
        conn = _get_db()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("SELECT phone_number FROM user_roles WHERE username = %s", (username.lower(),))
                row = cur.fetchone()
                profile["phone_number"] = row[0] if row else None
            finally:
                cur.close()
                conn.close()
    return _json(profile)


@app.route("/api/users/me", methods=["GET"])
@login_required
def get_me():
    return redirect(url_for("get_user", username=session["username"]))


@app.route("/api/users/search", methods=["GET"])
@require_auth
def search_users():
    """Autocomplete endpoint — returns usernames matching query."""
    q = request.args.get("q", "").strip()[:50]
    if len(q) < 2:
        return _json([])
    from services import _get_db
    conn = _get_db()
    if not conn:
        return _json([])
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT username FROM user_roles WHERE username ILIKE %s "
            "UNION "
            "SELECT username FROM users WHERE username ILIKE %s "
            "ORDER BY 1 LIMIT 10",
            (f"%{q}%", f"%{q}%"),
        )
        return _json([r[0] for r in cur.fetchall()])
    except Exception:
        return _json([])
    finally:
        try: cur.close()
        except Exception: pass
        conn.close()


@app.route("/api/users/me/phone", methods=["POST"])
@login_required
def update_phone():
    from services import set_phone_number
    data  = request.get_json() or {}
    phone = data.get("phone", "").strip()
    if not phone:
        from services import _get_db
        conn = _get_db()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE user_roles SET phone_number = NULL WHERE username = %s",
                    (session["username"],)
                )
                conn.commit()
            finally:
                cur.close()
                conn.close()
        return _json({"ok": True, "message": "Phone number removed."})
    ok, error = set_phone_number(session["username"], phone)
    if error:
        return _json({"error": error}, 400)
    return _json({"ok": True, "message": "Phone number saved. You'll receive SMS loan reminders."})


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
                COALESCE(SUM(amount), 0)                                    AS total_volume,
                COALESCE(SUM(amount_repaid), 0)                             AS total_repaid,
                COALESCE(SUM(amount) FILTER (
                    WHERE status IN ('confirmed','partially_repaid','unpaid')), 0) AS outstanding
            FROM loans
        """)
        row = cur.fetchone()

        cur.execute("SELECT COUNT(*) FROM disputes WHERE status = 'open'")
        open_disputes = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM role_requests WHERE status = 'pending'")
        pending_requests = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*) FROM loans
            WHERE due_date IS NOT NULL AND due_date < NOW()
              AND status NOT IN ('repaid', 'refunded', 'unpaid')
        """)
        overdue_loans = cur.fetchone()[0]

        return _json({
            "total_loans":       row[0], "active_loans":    row[1],
            "partial_loans":     row[2], "unpaid_loans":    row[3],
            "repaid_loans":      row[4], "refunded_loans":  row[5],
            "total_volume":      row[6], "total_repaid":    row[7],
            "outstanding":       row[8],
            "open_disputes":     open_disputes,
            "pending_requests":  pending_requests,
            "overdue_loans":     overdue_loans,
        })
    finally:
        cur.close()
        conn.close()


@app.route("/api/analytics", methods=["GET"])
@require_mod_api
def get_analytics():
    from services import _get_db
    conn = _get_db()
    if not conn:
        return _json({"error": "Database connection failed"}, 500)
    try:
        cur = conn.cursor()

        # Monthly loan volume for last 12 months
        cur.execute("""
            SELECT
                TO_CHAR(DATE_TRUNC('month', date_created), 'YYYY-MM') AS month,
                COUNT(*)                                               AS loan_count,
                COALESCE(SUM(amount), 0)                              AS volume,
                COALESCE(SUM(amount_repaid), 0)                       AS recovered,
                COUNT(*) FILTER (WHERE status = 'repaid')             AS repaid_count,
                COUNT(*) FILTER (WHERE status = 'unpaid')             AS unpaid_count
            FROM loans
            WHERE date_created >= NOW() - INTERVAL '12 months'
            GROUP BY month
            ORDER BY month
        """)
        monthly = [
            {"month": r[0], "loan_count": r[1], "volume": r[2],
             "recovered": r[3], "repaid_count": r[4], "unpaid_count": r[5]}
            for r in cur.fetchall()
        ]

        # Avg repayment time (days) for fully repaid loans
        cur.execute("""
            SELECT AVG(EXTRACT(EPOCH FROM (date_repaid - date_created)) / 86400)
            FROM loans
            WHERE status = 'repaid' AND date_repaid IS NOT NULL
        """)
        avg_days_row = cur.fetchone()
        avg_repayment_days = round(float(avg_days_row[0]), 1) if avg_days_row and avg_days_row[0] else None

        # Overall recovery rate
        cur.execute("""
            SELECT
                COALESCE(SUM(amount), 0)         AS total_lent,
                COALESCE(SUM(amount_repaid), 0)  AS total_recovered
            FROM loans
        """)
        totals = cur.fetchone()
        total_lent = float(totals[0]) if totals else 0
        total_recovered = float(totals[1]) if totals else 0
        recovery_rate = round(total_recovered / total_lent * 100, 1) if total_lent > 0 else 0

        # Top 5 lenders by volume
        cur.execute("""
            SELECT lender, COUNT(*) AS loans, SUM(amount) AS volume
            FROM loans GROUP BY lender ORDER BY volume DESC LIMIT 5
        """)
        top_lenders = [{"lender": r[0], "loans": r[1], "volume": r[2]} for r in cur.fetchall()]

        return _json({
            "monthly": monthly,
            "avg_repayment_days": avg_repayment_days,
            "recovery_rate": recovery_rate,
            "total_lent": total_lent,
            "total_recovered": total_recovered,
            "top_lenders": top_lenders,
        })
    except Exception as e:
        return _json({"error": str(e)}, 500)
    finally:
        cur.close()
        conn.close()


@app.route("/api/stats/lender/<lender>", methods=["GET"])
@require_auth
def get_lender_stats(lender):
    from services import get_lender_stats
    if session.get("username") and session.get("role") not in ("mod",):
        if lender.lower() != session["username"]:
            return _json({"error": "You can only view your own stats."}, 403)
    stats, error = get_lender_stats(lender)
    if error:
        return _json({"error": error}, 500)
    return _json(stats)


@app.route("/api/stats/borrower/<borrower>", methods=["GET"])
@require_auth
def get_borrower_stats(borrower):
    from services import get_borrower_stats as _get_borrower_stats
    if session.get("username") and session.get("role") != "mod":
        if borrower.lower() != session["username"]:
            return _json({"error": "You can only view your own stats."}, 403)
    stats, error = _get_borrower_stats(borrower)
    if error:
        return _json({"error": error}, 500)
    return _json(stats)


@app.route("/api/loans/overdue", methods=["GET"])
@require_mod_api
def get_overdue_loans():
    """Return active loans past their due date."""
    from services import _get_db
    conn = _get_db()
    if not conn:
        return _json({"error": "Database connection failed"}, 500)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, loan_id, lender, borrower, amount, amount_repaid,
                   currency, status, date_created, due_date
            FROM loans
            WHERE due_date IS NOT NULL
              AND due_date < NOW()
              AND status NOT IN ('repaid', 'refunded', 'unpaid')
            ORDER BY due_date ASC
            LIMIT 200
        """)
        rows = cur.fetchall()
        return _json([
            {
                "db_id": r[0], "loan_id": r[1], "lender": r[2], "borrower": r[3],
                "amount": r[4], "amount_repaid": r[5], "currency": r[6],
                "status": r[7], "date_created": r[8], "due_date": r[9],
                "days_overdue": (datetime.utcnow().date() - r[9].date()).days if r[9] else 0,
            }
            for r in rows
        ])
    except Exception as e:
        return _json({"error": str(e)}, 500)
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Public profile page
# ---------------------------------------------------------------------------

@app.route("/u/<username>")
@login_required
def user_profile(username):
    from services import get_user_profile, get_loan_history, calculate_health_score
    username = username.lower()
    profile, error = get_user_profile(username)
    if error or profile is None:
        flash(f"Could not load profile for u/{username}.", "error")
        return redirect(url_for("home"))
    score, label = calculate_health_score(profile)
    loans, _ = get_loan_history(username, role="both", limit=50)
    return render_template(
        "profile.html",
        target=username,
        profile=profile,
        score=score,
        score_label=label,
        loans=loans or [],
        viewer=session["username"],
        role=session["role"],
    )


# ---------------------------------------------------------------------------
# CSV export (mod only)
# ---------------------------------------------------------------------------

@app.route("/api/loans/export.csv")
@require_mod_api
def export_loans_csv():
    import csv
    import io
    loans, error = _get_all_loans_from_db(limit=10000)
    if error:
        return _json({"error": error}, 500)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "loan_id", "lender", "borrower", "amount", "amount_repaid",
        "remaining", "currency", "status", "date_created", "due_date",
        "date_repaid", "original_thread",
    ])
    for loan in loans:
        writer.writerow([
            loan["loan_id"], loan["lender"], loan["borrower"],
            float(loan["amount"]), float(loan.get("amount_repaid", 0)),
            float(loan["remaining"]), loan["currency"], loan["status"],
            loan["date_created"].isoformat() if loan.get("date_created") else "",
            loan["due_date"].isoformat() if loan.get("due_date") else "",
            loan["date_repaid"].isoformat() if loan.get("date_repaid") else "",
            loan.get("original_thread") or "",
        ])
    return app.response_class(
        response=buf.getvalue(),
        status=200,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=loancentral_export.csv"},
    )


@app.route("/api/loans/my-export.csv")
@login_required
def export_my_loans_csv():
    """Let lenders export their own loan history as CSV."""
    import csv
    import io
    from services import get_loan_history
    username = session["username"]
    loans, error = get_loan_history(username, role="lender", limit=10000)
    if error:
        return _json({"error": error}, 500)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "loan_id", "borrower", "amount", "amount_repaid", "remaining",
        "currency", "status", "date_created", "due_date", "date_repaid",
        "original_thread",
    ])
    for loan in loans:
        amt     = float(loan["amount"])
        repaid  = float(loan.get("amount_repaid", 0))
        writer.writerow([
            loan.get("loan_id") or loan.get("db_id"),
            loan["borrower"],
            amt, repaid, round(amt - repaid, 2),
            loan["currency"], loan["status"],
            loan["date_created"].isoformat() if loan.get("date_created") else "",
            loan["due_date"].isoformat()     if loan.get("due_date")     else "",
            loan["date_repaid"].isoformat()  if loan.get("date_repaid")  else "",
            loan.get("original_thread") or "",
        ])
    return app.response_class(
        response=buf.getvalue(),
        status=200,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=my_loans_{username}.csv"},
    )


# ---------------------------------------------------------------------------
# Role requests
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/api/users/me/delete-data", methods=["POST"])
@login_required
def delete_my_data():
    """Removes PII (phone, password hash, login timestamp) — keeps loan records."""
    from services import _get_db
    username = session["username"]
    conn = _get_db()
    if not conn:
        return _json({"error": "Database connection failed."}, 500)
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE user_roles
            SET phone_number = NULL, password_hash = NULL, last_login = NULL
            WHERE username = %s
        """, (username,))
        conn.commit()
        session.clear()
        return _json({"ok": True, "message": "Personal data removed. Loan records are retained for community integrity."})
    except Exception as e:
        conn.rollback()
        return _json({"error": str(e)}, 500)
    finally:
        cur.close()
        conn.close()


@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return _json({"error": "Not found."}, 404)
    return render_template("error.html", code=404,
                           message="Page not found.",
                           role=session.get("role", ""),
                           username=session.get("username", "")), 404


@app.errorhandler(403)
def forbidden(e):
    if request.path.startswith("/api/"):
        return _json({"error": "Forbidden."}, 403)
    return render_template("error.html", code=403,
                           message="You don't have permission to access this page.",
                           role=session.get("role", ""),
                           username=session.get("username", "")), 403


@app.errorhandler(500)
def server_error(e):
    if request.path.startswith("/api/"):
        return _json({"error": "Internal server error."}, 500)
    return render_template("error.html", code=500,
                           message="Something went wrong on our end.",
                           role=session.get("role", ""),
                           username=session.get("username", "")), 500


def _notify_mods_of_role_request(username, requested_role, reason):
    """DM the subreddit mods when a new role request comes in."""
    import os
    try:
        import praw
        reddit = praw.Reddit(
            client_id=os.getenv("REDDIT_CLIENT_ID"),
            client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
            username=os.getenv("REDDIT_USERNAME"),
            password=os.getenv("REDDIT_PASSWORD"),
            user_agent=os.getenv("REDDIT_USER_AGENT", f"LoanCentral/1.0 by u/{os.getenv('REDDIT_USERNAME', 'LoanBot')}"),
        )
        for sub in [s.strip() for s in os.getenv("SUBREDDITS", "").split(",") if s.strip()]:
            reddit.subreddit(sub).message(
                subject=f"[LoanCentral] New {requested_role} role request from u/{username}",
                message=(
                    f"u/{username} has requested **{requested_role}** access on the dashboard.\n\n"
                    f"**Reason:** {reason or 'No reason provided.'}\n\n"
                    f"Review it in the mod dashboard under the Requests tab."
                ),
            )
    except Exception as e:
        import logging
        logging.getLogger("LoanCentral").error(f"Failed to notify mods of role request: {e}")

    # Discord + email (fire-and-forget)
    try:
        from notifications import notify_discord, notify_email
        from config import DASHBOARD_URL
        notify_discord(
            f"\U0001f514 **Lender Request** — u/{username} requested {requested_role} access. "
            f"Reason: {reason[:120] if reason else 'none'}"
        )
        notify_email(
            f"New {requested_role} request from u/{username}",
            f"u/{username} requested {requested_role} access.\n\nReason: {reason or 'none'}\n\n"
            f"Review: {DASHBOARD_URL}/dashboard/mod"
        )
    except Exception as _e:
        import logging
        logging.getLogger("LoanCentral").warning(f"Role request notification failed: {_e}")


# ---------------------------------------------------------------------------
# Role requests
# ---------------------------------------------------------------------------

@app.route("/api/role-requests", methods=["POST"])
@login_required
def submit_role_request():
    from services import _get_db
    username = session["username"]
    data = request.get_json() or {}
    requested_role = data.get("role", "lender").strip().lower()
    reason = (data.get("reason") or "").strip()[:500]
    if requested_role not in ("lender",):
        return _json({"error": "Only lender role requests are supported."}, 400)
    conn = _get_db()
    if not conn:
        return _json({"error": "Database connection failed."}, 500)
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO role_requests (username, requested_role, reason, status, created_at)
            VALUES (%s, %s, %s, 'pending', NOW())
            ON CONFLICT (username) DO UPDATE
              SET requested_role = %s, reason = %s, status = 'pending', created_at = NOW()
        """, (username, requested_role, reason, requested_role, reason))
        conn.commit()
        _notify_mods_of_role_request(username, requested_role, reason)
        return _json({"ok": True, "message": "Request submitted. A mod will review it shortly."})
    except Exception as e:
        conn.rollback()
        return _json({"error": str(e)}, 500)
    finally:
        cur.close()
        conn.close()


@app.route("/api/role-requests", methods=["GET"])
@require_mod_api
def list_role_requests():
    from services import _get_db
    conn = _get_db()
    if not conn:
        return _json({"error": "Database connection failed."}, 500)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT username, requested_role, reason, status, created_at
            FROM role_requests WHERE status = 'pending'
            ORDER BY created_at ASC
        """)
        rows = cur.fetchall()
        return _json([
            {"username": r[0], "requested_role": r[1], "reason": r[2],
             "status": r[3], "created_at": r[4]}
            for r in rows
        ])
    except Exception as e:
        return _json({"error": str(e)}, 500)
    finally:
        cur.close()
        conn.close()


@app.route("/api/role-requests/<username>", methods=["POST"])
@require_mod_api
def resolve_role_request(username):
    from services import _get_db, set_user_role
    data = request.get_json() or {}
    action = data.get("action", "").lower()
    if action not in ("approve", "deny"):
        return _json({"error": "action must be 'approve' or 'deny'"}, 400)
    conn = _get_db()
    if not conn:
        return _json({"error": "Database connection failed."}, 500)
    try:
        cur = conn.cursor()
        cur.execute("SELECT requested_role FROM role_requests WHERE username = %s AND status = 'pending'",
                    (username,))
        row = cur.fetchone()
        if not row:
            return _json({"error": "No pending request found."}, 404)
        requested_role = row[0]
        cur.execute("UPDATE role_requests SET status = %s WHERE username = %s",
                    (action + "d", username))
        conn.commit()
        if action == "approve":
            set_user_role(username, requested_role)
        return _json({"ok": True, "action": action, "username": username})
    except Exception as e:
        conn.rollback()
        return _json({"error": str(e)}, 500)
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Admin: trigger SMS reminders
# ---------------------------------------------------------------------------

@app.route("/api/admin/send-reminders", methods=["POST"])
@require_mod_api
def trigger_reminders():
    """Manually trigger the SMS reminder job. Returns counts sent."""
    from services import get_loans_for_reminder, mark_reminder_sent, send_due_reminders
    from notifications import send_sms

    loans, error = get_loans_for_reminder()
    periodic_sent = 0
    if error:
        logger.warning(f"send-reminders: could not fetch periodic loans: {error}")
    else:
        DASHBOARD = os.getenv("DASHBOARD_URL", "")
        for loan in loans:
            try:
                if loan.get("reminder_type") == "unpaid":
                    msg = (
                        f"LoanCentral URGENT: Your loan of {loan['amount']:.2f} {loan['currency']} "
                        f"from u/{loan['lender']} (#{loan['loan_id']}) is marked UNPAID. "
                        f"Contact your lender to resolve. {DASHBOARD}"
                    )
                else:
                    msg = (
                        f"LoanCentral reminder: Outstanding loan of {loan['amount']:.2f} {loan['currency']} "
                        f"from u/{loan['lender']} (#{loan['loan_id']}). Arrange repayment. {DASHBOARD}"
                    )
                send_sms(loan["phone"], msg)
                mark_reminder_sent(loan["db_id"])
                periodic_sent += 1
            except Exception as e:
                logger.error(f"SMS reminder failed for loan {loan['loan_id']}: {e}")

    due_sent, due_error = send_due_reminders()
    if due_error:
        logger.warning(f"send-reminders: due-date reminders error: {due_error}")

    return _json({"ok": True, "periodic_sent": periodic_sent, "due_sent": due_sent or 0})


# ---------------------------------------------------------------------------
# Ban management
# ---------------------------------------------------------------------------

@app.route("/api/admin/bans", methods=["GET"])
@require_mod_api
def list_bans():
    from services import list_banned_users
    banned, error = list_banned_users()
    if error:
        return _json({"error": error}, 500)
    return _json({"banned": banned})


@app.route("/api/admin/bans/<username>", methods=["POST"])
@require_mod_api
def ban_user_api(username):
    data   = request.get_json(silent=True) or {}
    reason = (data.get("reason") or "").strip() or "No reason provided."
    actor  = session.get("username", "dashboard")
    from services import ban_user
    success, error = ban_user(username.lower(), reason, actor)
    if not success:
        return _json({"error": error}, 400)
    return _json({"ok": True, "username": username.lower(), "reason": reason})


@app.route("/api/admin/bans/<username>", methods=["DELETE"])
@require_mod_api
def unban_user_api(username):
    actor = session.get("username", "dashboard")
    from services import unban_user
    success, error = unban_user(username.lower(), actor)
    if not success:
        return _json({"error": error}, 400)
    return _json({"ok": True, "username": username.lower()})


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.route("/api/health")
def health_check():
    db_ok = False
    try:
        from services import _get_db
        conn = _get_db()
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            db_ok = True
            cur.close()
            conn.close()
    except Exception:
        pass

    bot = None
    try:
        from services import get_bot_status
        bot = get_bot_status()
    except Exception:
        pass

    status = "ok" if db_ok else "degraded"
    return _json({
        "status":  status,
        "db":      db_ok,
        "time":    datetime.utcnow().isoformat() + "Z",
        "version": "1.0.0",
        "bot":     bot,
    }, 200 if db_ok else 503)


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

@app.route("/leaderboard")
@login_required
def leaderboard_page():
    return render_template("leaderboard.html",
                           username=session["username"],
                           role=session["role"])


@app.route("/api/leaderboard")
@require_auth
def get_leaderboard():
    from services import get_leaderboard as _get_leaderboard
    data, error = _get_leaderboard()
    if error:
        return _json({"error": error}, 500)
    return _json(data)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

@app.route("/api/audit-log", methods=["GET"])
@require_mod_api
def get_audit_log():
    from services import get_audit_log as _get_audit_log
    limit  = min(int(request.args.get("limit", 100)), 500)
    offset = max(int(request.args.get("offset", 0)), 0)
    rows, error = _get_audit_log(limit=limit, offset=offset)
    if error:
        return _json({"error": error}, 500)
    return _json(rows)


# ---------------------------------------------------------------------------
# Loan applications
# ---------------------------------------------------------------------------

@app.route("/api/loan-applications", methods=["POST"])
@login_required
def create_loan_application():
    from services import submit_loan_application
    data = request.get_json() or {}
    try:
        amount = Decimal(str(data.get("amount", 0)))
    except Exception:
        return _json({"error": "Invalid amount."}, 400)
    if amount <= 0:
        return _json({"error": "Amount must be greater than zero."}, 400)
    currency = (data.get("currency") or "USD").upper()
    reason   = (data.get("reason") or "").strip()[:500]
    plan     = (data.get("repayment_plan") or "").strip()[:500]
    app_id, error = submit_loan_application(session["username"], amount, currency, reason, plan)
    if error:
        return _json({"error": error}, 500)
    return _json({"ok": True, "id": app_id, "message": "Application submitted. Lenders will be notified."})


@app.route("/api/loan-applications", methods=["GET"])
@require_auth
def list_loan_applications():
    from services import get_loan_applications
    status   = request.args.get("status")
    borrower = request.args.get("borrower")
    limit    = min(int(request.args.get("limit", 50)), 200)
    offset   = max(int(request.args.get("offset", 0)), 0)
    if session.get("role") not in ("mod", "lender") and not borrower:
        borrower = session.get("username")
    apps, error = get_loan_applications(status=status, borrower=borrower, limit=limit, offset=offset)
    if error:
        return _json({"error": error}, 500)
    return _json(apps)


@app.route("/api/loan-applications/<int:app_id>/claim", methods=["POST"])
@require_auth
def claim_loan_application(app_id):
    from services import update_loan_application, get_loan_applications
    if session.get("role") not in ("mod", "lender"):
        return _json({"error": "Only lenders can claim applications."}, 403)

    apps, _ = get_loan_applications()
    app_record = next((a for a in apps if a["id"] == app_id), None)
    if not app_record:
        return _json({"error": "Application not found."}, 404)
    if app_record.get("status") != "open":
        return _json({"error": f"Application is already {app_record.get('status')}."}, 400)
    if app_record["borrower"] == session["username"]:
        return _json({"error": "You cannot claim your own application."}, 400)

    ok, error = update_loan_application(app_id, "claimed", session["username"], lender=session["username"])
    if error:
        return _json({"error": error}, 400)

    lender   = session["username"]
    borrower = app_record["borrower"]
    amount   = float(app_record["amount"])
    currency = app_record["currency"]

    # Notify borrower via Reddit PM (fire-and-forget)
    try:
        from utils import reddit as _reddit
        _reddit.redditor(borrower).message(
            subject="Your LoanCentral application was claimed!",
            message=(
                f"Hi u/{borrower},\n\n"
                f"Your loan request for **{amount:.2f} {currency}** (Application #{app_id}) "
                f"has been claimed by u/{lender}.\n\n"
                f"Please reach out to u/{lender} to arrange the loan details.\n\n"
                f"---\n*LoanCentral Bot — reply with $help for commands*"
            )
        )
    except Exception as _e:
        logger.warning(f"Failed to PM borrower on application claim: {_e}")

    # Discord notification
    try:
        from notifications import notify_discord
        notify_discord(
            f"\U0001f91d **Application #{app_id} Claimed** — "
            f"u/{lender} → u/{borrower} | {amount:.2f} {currency}"
        )
    except Exception:
        pass

    return _json({"ok": True, "message": "Application claimed. Borrower has been notified."})


@app.route("/api/loan-applications/<int:app_id>/cancel", methods=["POST"])
@login_required
def cancel_loan_application(app_id):
    from services import get_loan_applications, update_loan_application
    apps, _ = get_loan_applications()
    app_record = next((a for a in apps if a["id"] == app_id), None)
    if not app_record:
        return _json({"error": "Application not found."}, 404)
    if session["username"] != app_record["borrower"] and session.get("role") != "mod":
        return _json({"error": "You can only cancel your own applications."}, 403)
    ok, error = update_loan_application(app_id, "cancelled", session["username"])
    if error:
        return _json({"error": error}, 400)
    return _json({"ok": True, "message": "Application cancelled."})


# ---------------------------------------------------------------------------
# Lender availability
# ---------------------------------------------------------------------------

@app.route("/api/users/me/availability", methods=["POST"])
@login_required
def set_availability():
    from services import set_lender_availability
    if session.get("role") not in ("mod", "lender"):
        return _json({"error": "Only lenders can toggle availability."}, 403)
    data      = request.get_json() or {}
    available = bool(data.get("available", True))
    ok, error = set_lender_availability(session["username"], available)
    if error:
        return _json({"error": error}, 500)
    return _json({"ok": True, "available": available})


@app.route("/api/lenders/available", methods=["GET"])
@require_auth
def list_available_lenders():
    from services import get_available_lenders
    lenders, error = get_available_lenders()
    if error:
        return _json({"error": error}, 500)
    return _json(lenders)


# ---------------------------------------------------------------------------
# Bulk loan actions (mod only)
# ---------------------------------------------------------------------------

@app.route("/api/loans/bulk", methods=["POST"])
@require_mod_api
def bulk_loan_action():
    from services import bulk_loan_action as _bulk
    data   = request.get_json() or {}
    ids    = data.get("ids", [])
    action = data.get("action", "").lower()
    actor  = session.get("username", "api")
    if not ids or action not in ("unpaid", "refunded"):
        return _json({"error": "ids (list) and action ('unpaid' or 'refunded') are required."}, 400)
    if len(ids) > 50:
        return _json({"error": "Maximum 50 loans per bulk action."}, 400)
    results = _bulk(ids, action, actor)
    return _json(results, 200 if results["failed"] == 0 else 207)


# ---------------------------------------------------------------------------
# Mod notes on loans
# ---------------------------------------------------------------------------

@app.route("/api/loans/<loan_id>/note", methods=["POST"])
@require_mod_api
def set_loan_note(loan_id):
    from services import add_loan_note
    data = request.get_json() or {}
    note = (data.get("note") or "").strip()
    ok, error = add_loan_note(loan_id, note or None, session.get("username", "api"))
    if error:
        return _json({"error": error}, 400)
    return _json({"ok": True, "message": "Note saved." if note else "Note cleared."})


# ---------------------------------------------------------------------------
# Dispute system
# ---------------------------------------------------------------------------

@app.route("/api/loans/<loan_id>/dispute", methods=["POST"])
@login_required
def file_dispute(loan_id):
    from services import submit_dispute
    data   = request.get_json() or {}
    reason = (data.get("reason") or "").strip()[:500]
    dispute_id, error = submit_dispute(loan_id, session["username"], reason)
    if error:
        return _json({"error": error}, 400)

    # Notify mods
    try:
        from notifications import notify_discord, notify_email
        from config import DASHBOARD_URL
        notify_discord(
            f"⚖️ **Dispute #{dispute_id} Filed** — u/{session['username']} "
            f"disputed loan #{loan_id}"
        )
        notify_email(
            f"Dispute #{dispute_id} filed on loan #{loan_id}",
            f"u/{session['username']} filed a dispute on loan #{loan_id}.\n\n"
            f"Reason: {reason or 'none'}\n\nReview: {DASHBOARD_URL}/dashboard/mod"
        )
    except Exception:
        pass

    return _json({"ok": True, "id": dispute_id,
                  "message": "Dispute filed. A mod will review it shortly."})


@app.route("/api/disputes", methods=["GET"])
@require_mod_api
def list_disputes():
    from services import get_disputes
    status = request.args.get("status", "open")
    limit  = min(int(request.args.get("limit", 50)), 200)
    offset = max(int(request.args.get("offset", 0)), 0)
    rows, error = get_disputes(status=status, limit=limit, offset=offset)
    if error:
        return _json({"error": error}, 500)
    return _json(rows)


@app.route("/api/disputes/<int:dispute_id>/resolve", methods=["POST"])
@require_mod_api
def resolve_dispute_route(dispute_id):
    from services import resolve_dispute
    data       = request.get_json() or {}
    action     = data.get("action", "").lower()
    resolution = (data.get("resolution") or "").strip()[:500]
    if action not in ("accept", "dismiss"):
        return _json({"error": "action must be 'accept' or 'dismiss'"}, 400)
    actor = session.get("username", "mod")
    ok, error = resolve_dispute(dispute_id, action, actor, resolution)
    if error:
        return _json({"error": error}, 400)

    try:
        from notifications import notify_discord
        verb = "Accepted" if action == "accept" else "Dismissed"
        notify_discord(
            f"⚖️ **Dispute #{dispute_id} {verb}** by mod u/{actor}"
        )
    except Exception:
        pass

    return _json({"ok": True, "action": action})


if __name__ == "__main__":
    port  = int(os.getenv("API_PORT", 5000))
    debug = IS_DEV
    app.run(host="0.0.0.0", port=port, debug=debug)
