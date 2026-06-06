import argparse
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def parse_args():
    parser = argparse.ArgumentParser(description="Initialize the LoanCentral test database schema.")
    parser.add_argument(
        "--env-file",
        default=str(ROOT / ".env.test"),
        help="Path to test env file. Defaults to .env.test.",
    )
    return parser.parse_args()


def assert_test_database():
    db_name = os.getenv("DB_NAME", "")
    env_name = os.getenv("LOANCENTRAL_ENV", "")
    safe_name = any(part in db_name.lower() for part in ("test", "dev", "stage", "staging"))
    if env_name.lower() == "test" or safe_name:
        return

    raise RuntimeError(
        "Refusing to initialize schema because DB_NAME does not look like a test/dev/staging database."
    )


def get_connection():
    assert_test_database()
    host = os.getenv("DB_HOST", "localhost")
    ssl_mode = "require" if any(name in host for name in ("render.com", "amazonaws.com", "heroku.com")) else "prefer"
    return psycopg2.connect(
        host=host,
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        sslmode=ssl_mode,
    )


def load_schema():
    schema_path = ROOT / "schema.sql"
    return schema_path.read_text(encoding="utf-8")


def main():
    args = parse_args()
    load_dotenv(args.env_file)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(load_schema())
        conn.commit()
    finally:
        conn.close()

    print(f"Initialized schema for test database: {os.getenv('DB_NAME')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
