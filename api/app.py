"""
LoanCentral API
---------------
REST API wrapping the service layer.
Serves the mod dashboard at /.
"""

import json
import os
import sys
from datetime import datetime
from decimal import Decimal
from functools import wraps

# Allow importing services and utils from parent directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

app = Flask(__name__)

API_KEY = os.getenv("API_KEY", "changeme")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serial(obj):
    """JSON serializer for Decimal and datetime."""
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


def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-API-Key") or request.args.get("api_key")
        if key != API_KEY:
            return _json({"error": "Unauthorized. Provide X-API-Key header."}, 401)
        return f(*args, **kwargs)
    return decorated


def _get_all_loans_from_db(status=None, search=None, limit=200):
    from services import _get_db
    conn = _get_db()
    if not conn:
        return None, "Database connection failed"
    try:
        cur = conn.cursor()
        conditions = []
        params = []
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
        loans = [
            {
                "db_id": r[0], "loan_id": r[1], "lender": r[2], "borrower": r[3],
                "amount": r[4], "amount_repaid": r[5], "currency": r[6],
                "status": r[7], "date_created": r[8], "original_thread": r[9],
                "remaining": Decimal(str(r[4])) - Decimal(str(r[5])),
            }
            for r in rows
        ]
        return loans, None
    except Exception as e:
        return None, str(e)
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    return render_template("dashboard.html")


# ---------------------------------------------------------------------------
# Loans
# ---------------------------------------------------------------------------

@app.route("/api/loans", methods=["GET"])
@require_api_key
def get_loans():
    from services import get_loan_history

    lender = request.args.get("lender")
    borrower = request.args.get("borrower")
    status = request.args.get("status")
    search = request.args.get("search")
    limit = int(request.args.get("limit", 200))

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
    return _json(loans)


@app.route("/api/loans/<loan_id>", methods=["GET"])
@require_api_key
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
        return _json({
            "db_id": row[0], "loan_id": row[1], "lender": row[2], "borrower": row[3],
            "amount": row[4], "amount_repaid": row[5], "currency": row[6],
            "status": row[7], "date_created": row[8], "original_thread": row[9],
            "remaining": Decimal(str(row[4])) - Decimal(str(row[5])),
        })
    finally:
        cur.close()
        conn.close()


@app.route("/api/loans/<loan_id>/unpaid", methods=["POST"])
@require_api_key
def set_loan_unpaid(loan_id):
    from services import mark_unpaid
    data = request.get_json() or {}
    lender = data.get("lender", "").strip().lower()
    if not lender:
        return _json({"error": "lender is required"}, 400)
    result, error = mark_unpaid(loan_id, lender)
    if error:
        return _json({"error": error}, 400)
    return _json(result)


@app.route("/api/loans/<loan_id>/refunded", methods=["POST"])
@require_api_key
def set_loan_refunded(loan_id):
    from services import mark_refunded_by_id
    data = request.get_json() or {}
    lender = data.get("lender", "").strip().lower()
    if not lender:
        return _json({"error": "lender is required"}, 400)
    result, error = mark_refunded_by_id(loan_id, lender)
    if error:
        return _json({"error": error}, 400)
    return _json(result)


@app.route("/api/loans/<loan_id>/paid", methods=["POST"])
@require_api_key
def set_loan_paid(loan_id):
    from services import mark_repaid
    data = request.get_json() or {}
    lender = data.get("lender", "").strip().lower()
    amount = data.get("amount")
    currency = data.get("currency", "").upper()
    if not all([lender, amount, currency]):
        return _json({"error": "lender, amount, and currency are required"}, 400)
    result, error = mark_repaid(loan_id, Decimal(str(amount)), currency, lender, actor_role="lender")
    if error:
        return _json({"error": error}, 400)
    return _json(result)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

@app.route("/api/users/<username>", methods=["GET"])
@require_api_key
def get_user(username):
    from services import get_user_profile, get_loan_history
    profile, error = get_user_profile(username)
    if error:
        return _json({"error": error}, 500)
    loans, _ = get_loan_history(username, role="both", limit=50)
    profile["recent_loans"] = loans or []
    return _json(profile)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@app.route("/api/stats", methods=["GET"])
@require_api_key
def get_stats():
    from services import _get_db
    conn = _get_db()
    if not conn:
        return _json({"error": "Database connection failed"}, 500)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                COUNT(*)                                            AS total,
                COUNT(*) FILTER (WHERE status = 'confirmed')       AS active,
                COUNT(*) FILTER (WHERE status = 'partially_repaid') AS partial,
                COUNT(*) FILTER (WHERE status = 'unpaid')          AS unpaid,
                COUNT(*) FILTER (WHERE status = 'repaid')          AS repaid,
                COUNT(*) FILTER (WHERE status = 'refunded')        AS refunded,
                COALESCE(SUM(amount), 0)                           AS total_volume,
                COALESCE(SUM(amount_repaid), 0)                    AS total_repaid,
                COALESCE(SUM(amount) FILTER (WHERE status IN ('confirmed','partially_repaid','unpaid')), 0) AS outstanding
            FROM loans
        """)
        row = cur.fetchone()
        return _json({
            "total_loans":     row[0],
            "active_loans":    row[1],
            "partial_loans":   row[2],
            "unpaid_loans":    row[3],
            "repaid_loans":    row[4],
            "refunded_loans":  row[5],
            "total_volume":    row[6],
            "total_repaid":    row[7],
            "outstanding":     row[8],
        })
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    port = int(os.getenv("API_PORT", 5000))
    debug = os.getenv("LOANCENTRAL_ENV", "prod") != "prod"
    app.run(host="0.0.0.0", port=port, debug=debug)
