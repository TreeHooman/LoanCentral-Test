"""
Applies schema.sql on startup. Runs before gunicorn starts.
Safe to run multiple times — CREATE TABLE IF NOT EXISTS handles re-runs.
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

def run():
    try:
        from utils import get_db_connection
        conn = get_db_connection()
        if not conn:
            print("WARNING: Could not connect to DB on startup — skipping schema apply")
            return

        with open(os.path.join(os.path.dirname(__file__), "schema.sql")) as f:
            sql = f.read()

        cur = conn.cursor()
        try:
            cur.execute(sql)
            conn.commit()
            print("Schema applied successfully.")
        except Exception as e:
            conn.rollback()
            print(f"Schema note (likely already exists): {e}")
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        print(f"WARNING: startup.py error (app will still start): {e}")

if __name__ == "__main__":
    run()
