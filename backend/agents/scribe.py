"""
scribe.py — SCRIBE Agent
Collects SENTINEL output, logs to PostgreSQL, generates narrative reports.
"""

import json
from datetime import datetime, timezone
from database.crud import save_sentinel_log, save_scribe_report, get_recent_sentinel_logs
from agents.sentinel import run_sentinel_direct
from data.sensor_generator import generate_snapshot


def _generate_narrative(result: dict) -> str:
    """
    Generate a human-readable narrative from SENTINEL result.

    WHY NARRATIVE?
    Factory operators are not data scientists.
    They need plain English reports, not JSON blobs.
    SCRIBE translates ML output into operator-friendly language.
    """
    ts = result.get("timestamp", datetime.now(timezone.utc).isoformat())
    status = result.get("status", "UNKNOWN")
    score = result.get("anomaly_score", 0.0)
    method = result.get("detection_method", "none")
    flagged = result.get("flagged_sensors", [])
    summary = result.get("summary", "")

    if status == "ANOMALY_DETECTED":
        sensor_list = ", ".join([s["sensor_id"] for s in flagged])
        severity = "CRITICAL" if score < -0.40 else "WARNING"
        narrative = (
            f"[{severity}] ANOMALY DETECTED at {ts}\n"
            f"  Detection Method : {method}\n"
            f"  Anomaly Score    : {score}\n"
            f"  Flagged Sensors  : {sensor_list}\n"
            f"  Assessment       : {summary}\n"
            f"  Action Required  : Inspect flagged sensors immediately."
        )
    else:
        narrative = (
            f"[OK] ALL SYSTEMS NORMAL at {ts}\n"
            f"  Anomaly Score : {score}\n"
            f"  Assessment    : {summary}"
        )
    return narrative


def run_scribe_cycle() -> dict:
    """
    Run one complete SCRIBE cycle:
    1. Get SENTINEL result
    2. Get raw snapshot
    3. Save to PostgreSQL
    4. Generate narrative report
    5. Save report to PostgreSQL
    6. Print report

    Returns dict with log_id, report_id, narrative.
    """
    snapshot = generate_snapshot(anomaly_probability=0.05)
    result = run_sentinel_direct()

    log = save_sentinel_log(result, snapshot)
    narrative = _generate_narrative(result)
    report = save_scribe_report(
        content=narrative,
        report_type="cycle",
        sentinel_log_id=log.id
    )

    print(narrative)
    return {
        "log_id":    log.id,
        "report_id": report.id,
        "status":    result["status"],
        "narrative": narrative,
    }


if __name__ == "__main__":
    print("=" * 60)
    print("SCRIBE Agent — Test Run")
    print("=" * 60)

    print("\n[TEST 1] Single SCRIBE cycle:")
    cycle = run_scribe_cycle()
    print(f"\n  Saved to DB — log_id={cycle['log_id']}, report_id={cycle['report_id']}")

    print("\n[TEST 2] 3 rapid cycles:")
    for i in range(3):
        print(f"\n--- Cycle {i+1} ---")
        run_scribe_cycle()

    print("\n[TEST 3] Recent logs from DB:")
    logs = get_recent_sentinel_logs(limit=5)
    for log in logs:
        print(f"  id={log.id} | {log.status:20} | score={log.anomaly_score} | {log.detection_method}")

    print("\nOK scribe.py working correctly")
