"""
crud.py — Create, Read, Update, Delete operations for CORTEX DB.

WHY SEPARATE CRUD FILE?
Keeps database logic separate from agent logic.
Agents call crud functions — they don't write SQL directly.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from database.models import SentinelLog, ScribeReport
from datetime import datetime, timezone

load_dotenv()

engine = create_engine(os.getenv("DATABASE_URL"))
SessionLocal = sessionmaker(bind=engine)


def save_sentinel_log(result: dict, snapshot: list = None) -> SentinelLog:
    """Save one SENTINEL detection result to PostgreSQL."""
    session = SessionLocal()
    try:
        log = SentinelLog(
            timestamp        = datetime.now(timezone.utc),
            status           = result.get("status", "UNKNOWN"),
            anomaly_score    = result.get("anomaly_score", 0.0),
            detection_method = result.get("detection_method", "none"),
            flagged_sensors  = result.get("flagged_sensors", []),
            summary          = result.get("summary", ""),
            raw_snapshot     = snapshot or [],
        )
        session.add(log)
        session.commit()
        session.refresh(log)
        return log
    finally:
        session.close()


def save_scribe_report(content: str, report_type: str = "cycle", sentinel_log_id: int = None) -> ScribeReport:
    """Save one SCRIBE narrative report to PostgreSQL."""
    session = SessionLocal()
    try:
        report = ScribeReport(
            timestamp       = datetime.now(timezone.utc),
            report_type     = report_type,
            content         = content,
            sentinel_log_id = sentinel_log_id,
        )
        session.add(report)
        session.commit()
        session.refresh(report)
        return report
    finally:
        session.close()


def get_recent_sentinel_logs(limit: int = 10) -> list:
    """Fetch most recent SENTINEL logs."""
    session = SessionLocal()
    try:
        return session.query(SentinelLog)\
                      .order_by(SentinelLog.id.desc())\
                      .limit(limit).all()
    finally:
        session.close()
