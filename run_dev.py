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

# Must import app AFTER env vars are set
from api.app import app

if __name__ == "__main__":
    print("Starting LoanCentral dev server...")
    print("Dev login: http://127.0.0.1:5000/auth/dev-login")
    print("Login page: http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=True)
