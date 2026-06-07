#!/usr/bin/env python3
"""
Bootstrap a dashboard user with a password.
Run this once to create your first mod account, then use the mod dashboard
to manage all other users.

Usage:
  python create_user.py <username> <role> <password>

Roles: mod, lender, borrower

Examples:
  python create_user.py yourusername mod MySecurePass123
  python create_user.py somelender lender Password456
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)

    username = sys.argv[1].strip().lower()
    role     = sys.argv[2].strip().lower()
    password = sys.argv[3]

    if role not in ("mod", "lender", "borrower"):
        print(f"Error: role must be mod, lender, or borrower (got '{role}')")
        sys.exit(1)

    if len(password) < 8:
        print("Error: password must be at least 8 characters")
        sys.exit(1)

    from services import set_user_role, set_password

    _, err = set_user_role(username, role)
    if err:
        print(f"Error setting role: {err}")
        sys.exit(1)

    _, err = set_password(username, password)
    if err:
        print(f"Error setting password: {err}")
        sys.exit(1)

    print(f"Done. u/{username} created as {role}.")
    print(f"They can log in at /login with username '{username}' and the password you set.")


if __name__ == "__main__":
    main()
