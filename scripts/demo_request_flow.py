"""Start an offline request-code demo with a new, disposable database each run."""
import argparse
import os
from pathlib import Path
import secrets
import sys
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5055)
    args = parser.parse_args()
    demo_dir = ROOT / "data" / ("request_demo_" + secrets.token_hex(6))
    demo_dir.mkdir()
    # Set every connection/credential setting before importing the app or services.
    os.environ.update({
        "LOANCENTRAL_ENV": "dev", "DB_BACKEND": "sqlite",
        "SQLITE_DB_PATH": str(demo_dir / "demo.sqlite3"), "DATABASE_URL": "",
        "DB_HOST": "", "DB_NAME": "", "DB_USER": "", "DB_PASSWORD": "",
        "REDDIT_MODE": "dry_run", "SUBREDDITS": "LoanCentralOfflineDemo",
        "REDDIT_CLIENT_ID": "", "REDDIT_CLIENT_SECRET": "",
        "REDDIT_USERNAME": "", "REDDIT_PASSWORD": "",
        "DASHBOARD_CLIENT_ID": "", "DASHBOARD_CLIENT_SECRET": "",
        "SECRET_KEY": secrets.token_hex(32), "API_KEY": "",
        "PUBLIC_DASHBOARD_TOKEN": "", "UPLOAD_DIR": str(demo_dir / "uploads"),
        "REMINDER_REDDIT_ENABLED": "false", "AUTO_BAN_REDDIT_ENABLED": "false",
        "REDDIT_FLAIR_SYNC_ENABLED": "false",
    })
    from local_db import get_sqlite_connection
    from services import save_loan_request
    conn = get_sqlite_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO user_roles (username, role, verified_lender) VALUES ('demo_lender', 'lender', TRUE)")
    cur.execute("INSERT INTO user_roles (username, role) VALUES ('demo_borrower', 'borrower')")
    conn.commit()
    conn.close()
    codes = []
    for index in range(2):
        code, error = save_loan_request(
            "demo_borrower", "[REQ] (150 CAD) (Repay 180 CAD) (2027-01-15) (Interac)",
            f"https://example.com/offline-request-{index}", datetime.now(), f"offline_demo_{index}")
        if error:
            raise SystemExit(error)
        codes.append(code)
    from api.app import app
    print(f"Offline demo database: {demo_dir}", flush=True)
    print(f"Lender: http://127.0.0.1:{args.port}/auth/dev-login-as/demo_lender", flush=True)
    for code in codes:
        print(f"Request: http://127.0.0.1:{args.port}/record-request/{code}", flush=True)
    app.run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
