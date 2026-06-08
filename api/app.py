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
# api directory on path so we can import auth
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
from flask import (Flask, flash, redirect, render_template,
                   request, session, url_for)

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))
app.permanent_session_lifetime = timedelta(days=7)

API_KEY = os.getenv("API_KEY", "changeme")
IS_DEV  = os.getenv("LOANCENTRAL_ENV", "prod") != "prod"


def _run_migrations():
    """Apply incremental schema changes that are safe to re-run."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from services import _get_db
        conn = _get_db()
        if not conn:
            return
        cur = conn.cursor()
        migrations = [
            "ALTER TABLE loans ADD COLUMN IF NOT EXISTS notes TEXT",
            "ALTER TABLE loans ADD COLUMN IF NOT EXISTS due_date DATE",
            "CREATE INDEX IF NOT EXISTS idx_loans_lender_status ON loans(lender, status)",
            "CREATE INDEX IF NOT EXISTS idx_loans_borrower_status ON loans(borrower, status)",
            "CREATE INDEX IF NOT EXISTS idx_loans_status_date ON loans(status, date_created DESC)",
        ]
        for sql in migrations:
            cur.execute(sql)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        import logging
        logging.getLogger("LoanCentral").warning(f"Migration warning: {e}")


_run_migrations()


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
        # Support comma-separated status values (e.g. "confirmed,partially_repaid")
        if status:
            statuses = [s.strip() for s in status.split(",") if s.strip()]
            if len(statuses) == 1:
                conditions.append("status = %s")
                params.append(statuses[0])
            else:
                placeholders = ",".join(["%s"] * len(statuses))
                conditions.append(f"status IN ({placeholders})")
                params.extend(statuses)
        if search:
            conditions.append("(lender ILIKE %s OR borrower ILIKE %s)")
            params += [f"%{search}%", f"%{search}%"]
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(limit)
        cur.execute(f"""
            SELECT id, loan_id, lender, borrower, amount, amount_repaid,
                   currency, status, date_created, original_thread, last_updated, notes, due_date
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
                "last_updated": r[10], "notes": r[11], "due_date": r[12],
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


@app.route("/auth/dev-seed")
def auth_dev_seed():
    """Dev-only: seed the database with test users and loans."""
    if not IS_DEV:
        return redirect(url_for("login"))
    from services import _get_db
    conn = _get_db()
    if not conn:
        return "<h2>DB connection failed</h2>", 500
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO user_roles (username, role) VALUES
              ('testmod', 'mod'), ('testlender', 'lender'),
              ('testlender2', 'lender'), ('testborrower', 'borrower'),
              ('testborrower2', 'borrower'), ('testborrower3', 'borrower')
            ON CONFLICT (username) DO NOTHING
        """)
        cur.execute("""
            INSERT INTO loans (loan_id, lender, borrower, amount, amount_repaid, currency, status, date_created, original_thread, notes) VALUES
              ('LC-TEST1','testlender','testborrower',200.00,50.00,'USD','partially_repaid',NOW()-INTERVAL'5 days','https://reddit.com/r/test/comments/abc1','Car repair loan'),
              ('LC-TEST2','testlender','testborrower2',100.00,0.00,'USD','confirmed',NOW()-INTERVAL'2 days','https://reddit.com/r/test/comments/abc2',NULL),
              ('LC-TEST3','testlender2','testborrower',500.00,0.00,'GBP','unpaid',NOW()-INTERVAL'45 days','https://reddit.com/r/test/comments/abc3','Overdue — 45 days'),
              ('LC-TEST4','testlender','testborrower3',75.00,75.00,'USD','repaid',NOW()-INTERVAL'15 days','https://reddit.com/r/test/comments/abc4',NULL),
              ('LC-TEST5','testlender2','testborrower',300.00,100.00,'USD','disputed',NOW()-INTERVAL'7 days','https://reddit.com/r/test/comments/abc5',NULL),
              ('LC-TEST6','testlender','testborrower',50.00,0.00,'CAD','confirmed',NOW()-INTERVAL'1 day','https://reddit.com/r/test/comments/abc6','Rent shortfall'),
              ('LC-TEST7','testlender','testborrower2',250.00,250.00,'USD','repaid',NOW()-INTERVAL'20 days','https://reddit.com/r/test/comments/abc7',NULL)
            ON CONFLICT (loan_id) DO NOTHING
        """)
        conn.commit()
        return """
        <html><body style="background:#0f1117;color:#e2e6f0;font-family:sans-serif;padding:40px;text-align:center">
        <h2 style="color:#2ecc71">Test data seeded!</h2>
        <p>Logins: <code>testmod</code> / <code>testlender</code> / <code>testborrower</code></p>
        <a href="/auth/dev-login" style="color:#7b8cff">Go to dev login →</a>
        </body></html>
        """
    except Exception as e:
        conn.rollback()
        return f"<h2>Error: {e}</h2>", 500
    finally:
        cur.close()
        conn.close()


@app.route("/api-docs")
@login_required
def api_docs():
    return render_template("api_docs.html", username=session["username"], role=session.get("role", "borrower"))


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

@app.route("/api/admin/migrate", methods=["POST"])
@require_mod_api
def run_migrations():
    """Re-run schema migrations — safe to call multiple times."""
    try:
        _run_migrations()
        return _json({"ok": True, "message": "Migrations applied."})
    except Exception as e:
        return _json({"error": str(e)}, 500)


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

@app.route("/api/loans", methods=["POST"])
@require_auth
def create_loan_api():
    from services import create_loan
    role = session.get("role")
    if role not in ("lender", "mod"):
        return _json({"error": "Only lenders can create loans."}, 403)
    data = request.get_json() or {}
    # Mods can specify a different lender; others always use their own username
    if role == "mod" and data.get("_lender_override"):
        lender = data["_lender_override"].strip().lower().lstrip("u/")
    else:
        lender = session.get("username", "").strip().lower()
    borrower   = (data.get("borrower") or "").strip().lower().lstrip("u/")
    currency   = (data.get("currency") or "USD").strip().upper()
    thread     = (data.get("thread_url") or "").strip() or "https://loancentral.app/dashboard"
    notes      = (data.get("notes") or "").strip() or None
    due_date   = (data.get("due_date") or "").strip() or None
    raw_amount = data.get("amount")
    if not lender:
        return _json({"error": "Lender username is required."}, 400)
    if not borrower:
        return _json({"error": "Borrower username is required."}, 400)
    if not raw_amount:
        return _json({"error": "Amount is required."}, 400)
    try:
        amount = Decimal(str(raw_amount))
    except Exception:
        return _json({"error": "Invalid amount."}, 400)
    loan_id, error = create_loan(lender, borrower, amount, currency, thread, notes=notes, due_date=due_date)
    if error:
        return _json({"error": error}, 400)
    return _json({"loan_id": loan_id, "ok": True}), 201


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
                   currency, status, date_created, original_thread, last_updated, notes, due_date
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
            "last_updated": row[10], "notes": row[11], "due_date": row[12],
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


@app.route("/api/loans/<loan_id>/dispute/resolve", methods=["POST"])
@require_mod_api
def resolve_dispute_endpoint(loan_id):
    from services import resolve_dispute
    data = request.get_json() or {}
    mod = session.get("username") or data.get("mod", "system")
    final_status = data.get("final_status", "").strip().lower()
    result, error = resolve_dispute(loan_id, mod, final_status)
    if error:
        return _json({"error": error}, 400)
    return _json(result)


@app.route("/api/loans/<loan_id>/notes", methods=["PATCH"])
@require_auth
def update_notes(loan_id):
    from services import update_loan_notes
    data      = request.get_json() or {}
    actor     = session.get("username", "").strip().lower()
    role      = session.get("role", "borrower")
    notes_val = (data.get("notes") or "").strip()
    result, error = update_loan_notes(loan_id, actor, role, notes_val)
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


@app.route("/api/loans/<loan_id>/forgive", methods=["POST"])
@require_auth
def forgive_loan_endpoint(loan_id):
    from services import forgive_loan
    data   = request.get_json() or {}
    lender = data.get("lender", session.get("username", "")).strip().lower()
    if session.get("role") == "mod" and data.get("lender"):
        lender = data["lender"].strip().lower()
    if not lender:
        return _json({"error": "lender is required"}, 400)
    result, error = forgive_loan(loan_id, lender)
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


@app.route("/api/users/<username>/profile", methods=["GET"])
@require_auth
def get_user_public_profile(username):
    """Public borrower profile — available to any authenticated user."""
    from services import get_user_profile
    profile, error = get_user_profile(username)
    if error:
        return _json({"error": error}, 500)
    # Also fetch last_login from user_roles
    last_login = None
    from services import _get_db
    conn = _get_db()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT last_login FROM user_roles WHERE username = %s", (username.lower(),))
            row = cur.fetchone()
            if row:
                last_login = row[0]
        except Exception:
            pass
        finally:
            cur.close(); conn.close()
    return _json({
        "username": username,
        "loans_as_borrower": profile.get("loans_as_borrower", 0),
        "unpaid_loans": profile.get("unpaid_loans", 0),
        "amount_borrowed": profile.get("amount_borrowed", 0),
        "amount_repaid": profile.get("amount_repaid", 0),
        "active_amount": profile.get("active_amount", 0),
        "last_login": last_login,
    })


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
                COUNT(*) FILTER (WHERE status = 'disputed')                 AS disputed,
                COALESCE(SUM(amount), 0)                                    AS total_volume,
                COALESCE(SUM(amount_repaid), 0)                             AS total_repaid,
                COALESCE(SUM(amount) FILTER (
                    WHERE status IN ('confirmed','partially_repaid','unpaid')), 0) AS outstanding,
                COUNT(*) FILTER (WHERE date_created >= NOW() - INTERVAL '7 days') AS new_this_week,
                COUNT(*) FILTER (WHERE status IN ('confirmed','partially_repaid')
                    AND date_created < NOW() - INTERVAL '30 days')          AS overdue_30d
            FROM loans
        """)
        row = cur.fetchone()
        return _json({
            "total_loans":    row[0], "active_loans":  row[1],
            "partial_loans":  row[2], "unpaid_loans":  row[3],
            "repaid_loans":   row[4], "refunded_loans": row[5],
            "disputed_loans": row[6],
            "total_volume":   row[7], "total_repaid":  row[8],
            "outstanding":    row[9], "new_this_week": row[10],
            "overdue_30d":    row[11],
        })
    finally:
        cur.close()
        conn.close()


@app.route("/api/leaderboard", methods=["GET"])
@require_auth
def get_leaderboard():
    from services import _get_db
    conn = _get_db()
    if not conn:
        return _json({"error": "Database connection failed"}, 500)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT lender,
                   COUNT(*) FILTER (WHERE status NOT IN ('refunded')) AS loans,
                   COALESCE(SUM(amount) FILTER (WHERE status NOT IN ('refunded')), 0) AS total_lent,
                   COALESCE(SUM(amount_repaid), 0) AS total_recovered,
                   COUNT(*) FILTER (WHERE status = 'repaid') AS repaid_count,
                   COUNT(*) FILTER (WHERE status = 'unpaid') AS unpaid_count
            FROM loans
            WHERE status NOT IN ('refunded')
            GROUP BY lender
            HAVING COUNT(*) FILTER (WHERE status NOT IN ('refunded')) >= 1
            ORDER BY total_lent DESC
            LIMIT 10
        """)
        top_lenders = [
            {"username": r[0], "loans": r[1], "total_lent": r[2],
             "total_recovered": r[3], "repaid": r[4], "unpaid": r[5]}
            for r in cur.fetchall()
        ]
        cur.execute("""
            SELECT borrower,
                   COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE status = 'repaid') AS repaid,
                   COUNT(*) FILTER (WHERE status = 'unpaid') AS unpaid,
                   COALESCE(SUM(amount_repaid), 0) AS amount_repaid,
                   COALESCE(SUM(amount), 0) AS amount_borrowed
            FROM loans
            WHERE status NOT IN ('refunded')
            GROUP BY borrower
            HAVING COUNT(*) >= 2
            ORDER BY
                COUNT(*) FILTER (WHERE status = 'unpaid') ASC,
                (COUNT(*) FILTER (WHERE status = 'repaid')::float /
                 NULLIF(COUNT(*) FILTER (WHERE status NOT IN ('refunded','disputed')),0)) DESC NULLS LAST,
                COUNT(*) DESC
            LIMIT 10
        """)
        top_borrowers = [
            {"username": r[0], "total": r[1], "repaid": r[2],
             "unpaid": r[3], "amount_repaid": r[4], "amount_borrowed": r[5]}
            for r in cur.fetchall()
        ]
        return _json({"top_lenders": top_lenders, "top_borrowers": top_borrowers})
    finally:
        cur.close()
        conn.close()


@app.route("/leaderboard")
@login_required
def leaderboard():
    return render_template("leaderboard.html",
                           username=session["username"],
                           role=session.get("role", "borrower"))


@app.route("/settings")
@login_required
def settings():
    return render_template("settings.html",
                           username=session["username"],
                           role=session.get("role", "borrower"),
                           api_key=API_KEY)


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


@app.route("/api/stats/lender/<lender>/monthly", methods=["GET"])
@require_auth
def get_lender_monthly(lender):
    """Monthly loan activity for the past 12 months."""
    from services import _get_db
    if session.get("username") and session.get("role") not in ("mod",):
        if lender.lower() != session["username"]:
            return _json({"error": "You can only view your own stats."}, 403)
    conn = _get_db()
    if not conn:
        return _json({"error": "Database connection failed"}, 500)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                TO_CHAR(DATE_TRUNC('month', date_created), 'YYYY-MM') AS month,
                COUNT(*) AS new_loans,
                COALESCE(SUM(amount), 0) AS volume_lent,
                COALESCE(SUM(amount_repaid), 0) AS recovered
            FROM loans
            WHERE lender = %s
              AND date_created >= NOW() - INTERVAL '12 months'
            GROUP BY DATE_TRUNC('month', date_created)
            ORDER BY DATE_TRUNC('month', date_created)
        """, (lender.lower(),))
        rows = cur.fetchall()
        return _json([
            {"month": r[0], "new_loans": r[1], "volume_lent": r[2], "recovered": r[3]}
            for r in rows
        ])
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return _json({"error": "Not found"}, 404)
    return render_template("error.html", code=404, message="Page not found."), 404


@app.errorhandler(500)
def server_error(e):
    if request.path.startswith("/api/"):
        return _json({"error": "Internal server error"}, 500)
    return render_template("error.html", code=500, message="Something went wrong on our end."), 500


@app.errorhandler(403)
def forbidden(e):
    if request.path.startswith("/api/"):
        return _json({"error": "Forbidden"}, 403)
    return render_template("error.html", code=403, message="You don't have permission to access this."), 403


if __name__ == "__main__":
    port  = int(os.getenv("API_PORT", 5000))
    debug = IS_DEV
    app.run(host="0.0.0.0", port=port, debug=debug)
