"""
init_db.py — Create all tables in PostgreSQL.
Run once to initialize the database schema.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import create_engine
from dotenv import load_dotenv
from database.models import Base

load_dotenv()


def init_db():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL not set in .env")

    print(f"[DB] Connecting to PostgreSQL...")
    engine = create_engine(db_url)

    print("[DB] Creating tables...")
    Base.metadata.create_all(engine)
    print("[DB] Tables created: sentinel_logs, scribe_reports")
    return engine


if __name__ == "__main__":
    init_db()
    print("OK database initialized")
