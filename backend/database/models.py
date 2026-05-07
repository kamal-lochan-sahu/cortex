"""
models.py — SQLAlchemy ORM models for CORTEX database.

WHY SQLALCHEMY ORM?
Instead of writing raw SQL, we define Python classes.
SQLAlchemy converts them to SQL automatically.
Same code works on SQLite (testing) and PostgreSQL (production).
"""

from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, JSON
from sqlalchemy.orm import declarative_base
from datetime import datetime, timezone

Base = declarative_base()


class SentinelLog(Base):
    """
    One row = one SENTINEL detection cycle result.
    Stores both the verdict and full sensor snapshot as JSON.
    """
    __tablename__ = "sentinel_logs"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    timestamp        = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    status           = Column(String(20), nullable=False)   # ANOMALY_DETECTED / ALL_NORMAL
    anomaly_score    = Column(Float, nullable=False)
    detection_method = Column(String(20), nullable=False)   # ml_score / rule_based / both / none
    flagged_sensors  = Column(JSON, default=list)           # list of flagged sensor dicts
    summary          = Column(Text, nullable=False)
    raw_snapshot     = Column(JSON, default=dict)           # full 14-sensor snapshot

    def __repr__(self):
        return f"<SentinelLog id={self.id} status={self.status} score={self.anomaly_score}>"


class ScribeReport(Base):
    """
    One row = one SCRIBE narrative report.
    SCRIBE generates these after each SENTINEL cycle.
    """
    __tablename__ = "scribe_reports"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    timestamp    = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    report_type  = Column(String(20), nullable=False)   # cycle / hourly / daily
    content      = Column(Text, nullable=False)          # narrative text
    sentinel_log_id = Column(Integer, nullable=True)     # FK to sentinel_logs

    def __repr__(self):
        return f"<ScribeReport id={self.id} type={self.report_type}>"
