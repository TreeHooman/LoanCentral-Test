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
        cur.execute(f"""
            SELECT id, loan_id, lender, borrower, amount, amount_repaid,
                   currency, status, date_created, original_thread
            FROM loans {where}
            ORDER BY date_created DESC LIMIT %s
        """, params)
        rows = cur.fetchall()
        return [
            {
                "db_id": r[0], "loan_id": r[1], "lender": r[2], "borrower": r[3],
                "amount": r[4], "amount_repaid": r[5], "currency": r[6],
                "status": r[7], "date_created": r[8], "original_thread": r[9],
                "remaining": Decimal(str(r[4])) - Decimal(str(r[5])),
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

    # Non-mods can only see their own data
    if session.get("username") and session.get("role") != "mod":
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
    from services import get_user_profile, get_loan_history
    # Scope check
    if session.get("username") and session.get("role") != "mod":
        if username.lower() != session["username"]:
            return _json({"error": "You can only view your own profile."}, 403)
    profile, error = get_user_profile(username)
    if error:
        return _json({"error": error}, 500)
    loans, _ = get_loan_history(username, role="both", limit=50)
    profile["recent_loans"] = loans or []
    return _json(profile)


@app.route("/api/users/me", methods=["GET"])
@login_required
def get_me():
    return redirect(url_for("get_user", username=session["username"]))


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
        return _json({
            "total_loans":    row[0], "active_loans":  row[1],
            "partial_loans":  row[2], "unpaid_loans":  row[3],
            "repaid_loans":   row[4], "refunded_loans": row[5],
            "total_volume":   row[6], "total_repaid":  row[7],
            "outstanding":    row[8],
        })
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
    writer.writerow(["loan_id", "lender", "borrower", "amount", "amount_repaid",
                     "remaining", "currency", "status", "date_created", "original_thread"])
    for loan in loans:
        writer.writerow([
            loan["loan_id"], loan["lender"], loan["borrower"],
            float(loan["amount"]), float(loan["amount_repaid"]),
            float(loan["remaining"]), loan["currency"], loan["status"],
            loan["date_created"].isoformat() if loan["date_created"] else "",
            loan["original_thread"] or "",
        ])
    output = buf.getvalue()
    return app.response_class(
        response=output,
        status=200,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=loancentral_export.csv"},
    )


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


if __name__ == "__main__":
    port  = int(os.getenv("API_PORT", 5000))
    debug = IS_DEV
    app.run(host="0.0.0.0", port=port, debug=debug)
