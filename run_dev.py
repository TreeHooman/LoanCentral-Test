"""
Dev server launcher — loads .env.test and starts Flask with LOANCENTRAL_ENV=dev
Run with: python run_dev.py
"""
import os
from dotenv import load_dotenv

# Load test environment
load_dotenv(".env.test", override=True)

# Force dev mode so dev login and debug features are enabled
os.environ["LOANCENTRAL_ENV"] = "dev"
os.environ["DB_NAME"] = "loancentral_dev"  # use local dev DB, not test or prod

# Must import app AFTER env vars are set
from api.app import app

if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5000"))
    print("Starting LoanCentral dev server...")
    print(f"Dev login: http://{host}:{port}/auth/dev-login")
    print(f"Login page: http://{host}:{port}")
    app.run(host=host, port=port, debug=True, use_reloader=False)
