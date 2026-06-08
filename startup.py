"""
Run DB migrations on startup (Render build step or first boot).
Usage: python startup.py
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

from utils import get_db_connection

def run():
    conn = get_db_connection()
    if not conn:
        print("ERROR: Cannot connect to database")
        sys.exit(1)

    with open("schema.sql") as f:
        sql = f.read()

    cur = conn.cursor()
    try:
        cur.execute(sql)
        conn.commit()
        print("Schema applied.")
    except Exception as e:
        conn.rollback()
        print(f"Schema error (may already exist): {e}")
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    run()
