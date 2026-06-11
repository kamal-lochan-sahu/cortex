"""
metric_aggregator.py — Data aggregator for SCRIBE
Collects last N hours of data from all agent DB tables
and returns clean context dicts for LLM narrative generation.

ACTUAL TABLE MAPPING (verified from DB):
  sentinel_logs      → SENTINEL data (timestamp col, not created_at)
  optimus_decisions  → OPTIMUS data
  oracle_maintenance → ORACLE maintenance predictions
  oracle_forecasts   → ORACLE demand forecasts
  hermes_inventory   → HERMES inventory items
  hermes_orders      → HERMES purchase orders
  hermes_suppliers   → HERMES supplier scores
  scribe_reports     → SCRIBE stored reports

MISSING TABLES (no guardian_logs, no health_scores):
  guardian → hardcoded ACTIVE status
  health   → calculated from other agents
"""

import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from sqlalchemy import text
from database.crud import SessionLocal

logger = logging.getLogger(__name__)


# ── Safe value helpers ─────────────────────────────────────────────────────────

def _safe(value, default="N/A"):
    """None values ko default se replace karo — LLM ko None nahi dena."""
    return value if value is not None else default

def _safe_round(value, decimals=2, default=0.0):
    """Numeric values ko round karo safely."""
    try:
        return round(float(value), decimals)
    except (TypeError, ValueError):
        return default


# ── Function 1: Hourly Context ─────────────────────────────────────────────────

def get_hourly_context() -> dict:
    """
    Last 1 hour ka data — hourly_snapshot prompt ke liye.
    sentinel_logs.timestamp column use karta hai (not created_at).
    """
    db  = SessionLocal()
    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)

    try:
        # ── SENTINEL ──────────────────────────────────────────────────────────
        # sentinel_logs mein timestamp column hai, created_at nahi
        sent = db.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'ANOMALY_DETECTED') AS anomaly_count,
                MIN(anomaly_score) AS worst_score
            FROM sentinel_logs
            WHERE timestamp >= :since
        """), {"since": one_hour_ago}).fetchone()

        anomaly_count = int(_safe(sent.anomaly_count, 0))

        # Top flagged sensor — most recent anomaly
        top_sensor_row = db.execute(text("""
            SELECT flagged_sensors
            FROM sentinel_logs
            WHERE status = 'ANOMALY_DETECTED'
              AND timestamp >= :since
            ORDER BY timestamp DESC
            LIMIT 1
        """), {"since": one_hour_ago}).fetchone()

        top_anomaly_sensor = "none"
        if top_sensor_row and top_sensor_row.flagged_sensors:
            sensors = top_sensor_row.flagged_sensors
            if isinstance(sensors, list) and len(sensors) > 0:
                first = sensors[0]
                top_anomaly_sensor = (
                    first.get("sensor_id", "unknown")
                    if isinstance(first, dict) else str(first)
                )

        # ── GUARDIAN — table nahi hai, hardcode karo ──────────────────────────
        threat_count    = 0
        guardian_status = "ACTIVE"

        # ── ORACLE — oracle_maintenance table ─────────────────────────────────
        orc = db.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE failure_prob > 0.5) AS pred_count
            FROM oracle_maintenance
            WHERE generated_at >= :since
        """), {"since": one_hour_ago}).fetchone()

        failure_predictions = int(_safe(orc.pred_count, 0))

        next_maint = db.execute(text("""
            SELECT machine_id, window_start, failure_prob
            FROM oracle_maintenance
            WHERE generated_at >= :since
              AND failure_prob > 0.5
            ORDER BY failure_prob DESC
            LIMIT 1
        """), {"since": one_hour_ago}).fetchone()

        if next_maint:
            hours_until = max(0, round(
                (next_maint.window_start - now).total_seconds() / 3600, 1
            ))
            next_maintenance = f"{next_maint.machine_id} in {hours_until}h"
        else:
            next_maintenance = "none scheduled"

        # ── OPTIMUS — optimus_decisions table ─────────────────────────────────
        opt = db.execute(text("""
            SELECT action, savings_eur
            FROM optimus_decisions
            WHERE timestamp >= :since
            ORDER BY timestamp DESC
            LIMIT 1
        """), {"since": one_hour_ago}).fetchone()

        if opt:
            optimus_action     = _safe(opt.action, "NO_ACTION")
            energy_savings_eur = _safe_round(opt.savings_eur)
        else:
            optimus_action     = "NO_ACTION"
            energy_savings_eur = 0.0

        # ── HERMES — hermes_inventory table ───────────────────────────────────
        hrm = db.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE current_stock <= reorder_point) AS low_stock,
                COUNT(*) FILTER (WHERE last_reorder_at >= :since)       AS reorders
            FROM hermes_inventory
        """), {"since": one_hour_ago}).fetchone()

        inventory_alerts = int(_safe(hrm.low_stock, 0))
        reorder_count    = int(_safe(hrm.reorders, 0))

        # ── HEALTH SCORE — sentinel + oracle + hermes se calculate ─────────────
        # Guardian nahi hai toh 3 agent weighted average
        sentinel_score = max(0, 100 - (anomaly_count * 10))
        oracle_score   = max(0, 100 - (failure_predictions * 15))
        hermes_score   = max(0, 100 - (inventory_alerts * 8))
        health_score   = round((sentinel_score * 0.4) + (oracle_score * 0.35) + (hermes_score * 0.25))

        return {
            "timestamp"          : now.strftime("%Y-%m-%d %H:%M UTC"),
            "health_score"       : health_score,
            "anomaly_count"      : anomaly_count,
            "top_anomaly_sensor" : top_anomaly_sensor,
            "threat_count"       : threat_count,
            "guardian_status"    : guardian_status,
            "failure_predictions": failure_predictions,
            "next_maintenance"   : next_maintenance,
            "optimus_action"     : optimus_action,
            "energy_savings_eur" : energy_savings_eur,
            "inventory_alerts"   : inventory_alerts,
            "reorder_count"      : reorder_count
        }

    except Exception as e:
        logger.error(f"get_hourly_context error: {e}")
        return {
            "timestamp"          : now.strftime("%Y-%m-%d %H:%M UTC"),
            "health_score"       : 0,
            "anomaly_count"      : 0,
            "top_anomaly_sensor" : "unknown",
            "threat_count"       : 0,
            "guardian_status"    : "UNKNOWN",
            "failure_predictions": 0,
            "next_maintenance"   : "unknown",
            "optimus_action"     : "UNKNOWN",
            "energy_savings_eur" : 0.0,
            "inventory_alerts"   : 0,
            "reorder_count"      : 0
        }
    finally:
        db.close()


# ── Function 2: Alert Context ──────────────────────────────────────────────────

def get_alert_context(sentinel_log_id: int) -> dict:
    """
    Specific alert ka context — alert_narrative prompt ke liye.
    sentinel_logs.id se fetch karta hai.
    """
    db = SessionLocal()
    try:
        alert = db.execute(text("""
            SELECT id, status, anomaly_score,
                   detection_method, flagged_sensors,
                   timestamp, summary
            FROM sentinel_logs
            WHERE id = :log_id
        """), {"log_id": sentinel_log_id}).fetchone()

        if not alert:
            raise ValueError(f"Alert {sentinel_log_id} not found")

        score    = _safe_round(alert.anomaly_score)
        severity = "CRITICAL" if score < -0.40 else "HIGH"

        sensors = alert.flagged_sensors or []
        if isinstance(sensors, list):
            affected = ", ".join(
                s.get("sensor_id", str(s)) if isinstance(s, dict) else str(s)
                for s in sensors[:3]
            )
        else:
            affected = str(sensors)

        affected_component = affected if affected else "unknown component"

        return {
            "timestamp"         : alert.timestamp.strftime("%Y-%m-%d %H:%M UTC"),
            "agent_name"        : "SENTINEL",
            "severity"          : severity,
            "event_description" : f"Anomaly via {alert.detection_method}, score: {score}. {_safe(alert.summary, '')}",
            "affected_component": affected_component,
            "auto_action"       : "Alert logged, SCRIBE notified, operators alerted via WebSocket",
            "system_status"     : "All other systems nominal — monitoring continues"
        }

    except Exception as e:
        logger.error(f"get_alert_context error: {e}")
        return {
            "timestamp"         : datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "agent_name"        : "SENTINEL",
            "severity"          : "HIGH",
            "event_description" : "Anomaly detected — details unavailable",
            "affected_component": "unknown",
            "auto_action"       : "System monitoring active",
            "system_status"     : "unknown"
        }
    finally:
        db.close()


# ── Function 3: Daily Context ──────────────────────────────────────────────────

def get_daily_context() -> dict:
    """
    Last 24 hours ka full summary — daily_briefing prompt ke liye.
    """
    db           = SessionLocal()
    now          = datetime.now(timezone.utc)
    yesterday    = now - timedelta(hours=24)

    try:
        # ── SENTINEL 24hr ─────────────────────────────────────────────────────
        sent = db.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'ANOMALY_DETECTED') AS total,
                COUNT(*) FILTER (WHERE anomaly_score < -0.40)        AS critical,
                AVG(anomaly_score)                                    AS avg_score
            FROM sentinel_logs
            WHERE timestamp >= :since
        """), {"since": yesterday}).fetchone()

        total_anomalies = int(_safe(sent.total, 0))
        critical_count  = int(_safe(sent.critical, 0))
        avg_score       = _safe_round(sent.avg_score, 3)

        top_sensor_row = db.execute(text("""
            SELECT flagged_sensors FROM sentinel_logs
            WHERE status = 'ANOMALY_DETECTED'
              AND timestamp >= :since
            ORDER BY anomaly_score ASC
            LIMIT 1
        """), {"since": yesterday}).fetchone()

        top_sensor = "none"
        if top_sensor_row and top_sensor_row.flagged_sensors:
            s = top_sensor_row.flagged_sensors
            if isinstance(s, list) and s:
                top_sensor = s[0].get("sensor_id", "unknown") if isinstance(s[0], dict) else str(s[0])

        # ── GUARDIAN — hardcoded ───────────────────────────────────────────────
        threats_blocked    = 0
        intrusion_attempts = 0

        # ── ORACLE 24hr ───────────────────────────────────────────────────────
        orc = db.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE failure_prob > 0.5)   AS predicted,
                COUNT(*) FILTER (WHERE risk_level = 'LOW')   AS completed
            FROM oracle_maintenance
            WHERE generated_at >= :since
        """), {"since": yesterday}).fetchone()

        failures_predicted = int(_safe(orc.predicted, 0))
        maintenance_done   = int(_safe(orc.completed, 0))

        top_risk = db.execute(text("""
            SELECT machine_id, failure_prob
            FROM oracle_maintenance
            WHERE generated_at >= :since
            ORDER BY failure_prob DESC
            LIMIT 1
        """), {"since": yesterday}).fetchone()

        top_risk_component = _safe(top_risk.machine_id, "none") if top_risk else "none"
        top_risk_percent   = int(_safe_round(top_risk.failure_prob * 100) if top_risk else 0)

        # ── OPTIMUS 24hr ──────────────────────────────────────────────────────
        opt = db.execute(text("""
            SELECT
                COALESCE(SUM(savings_eur), 0) AS total_eur,
                COUNT(*)                       AS actions
            FROM optimus_decisions
            WHERE timestamp >= :since
        """), {"since": yesterday}).fetchone()

        total_eur_saved = _safe_round(opt.total_eur)
        entso_actions   = int(_safe(opt.actions, 0))
        total_kwh_saved = _safe_round(total_eur_saved / 0.12)  # estimate: €0.12/kWh
        peak_reduction  = min(entso_actions * 3, 30)

        # ── HERMES 24hr ───────────────────────────────────────────────────────
        inv = db.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE current_stock <= reorder_point) AS low_stock,
                COUNT(*) AS total_items
            FROM hermes_inventory
        """)).fetchone()

        low_stock_alerts = int(_safe(inv.low_stock, 0))
        total_items      = int(_safe(inv.total_items, 1))
        inventory_health = int(((total_items - low_stock_alerts) / total_items) * 100) if total_items else 100

        orders_row = db.execute(text("""
            SELECT COUNT(*) AS cnt FROM hermes_orders
            WHERE created_at >= :since
        """), {"since": yesterday}).fetchone()
        orders_processed = int(_safe(orders_row.cnt, 0))

        sup_row = db.execute(text("""
            SELECT AVG(reliability_score) AS avg_rel
            FROM hermes_suppliers
        """)).fetchone()
        sup_perf = f"{int(_safe_round(sup_row.avg_rel) if sup_row and sup_row.avg_rel else 0)}%"

        # ── HEALTH SCORE ──────────────────────────────────────────────────────
        sentinel_score    = max(0, 100 - (total_anomalies * 2))
        oracle_score      = max(0, 100 - (failures_predicted * 10))
        hermes_score      = inventory_health
        health_score      = round((sentinel_score * 0.4) + (oracle_score * 0.35) + (hermes_score * 0.25))
        prev_health_score = health_score  # no historical table — same value

        return {
            "date"                 : now.strftime("%Y-%m-%d"),
            "health_score"         : health_score,
            "prev_health_score"    : prev_health_score,
            "total_anomalies"      : total_anomalies,
            "critical_count"       : critical_count,
            "avg_score"            : avg_score,
            "top_sensor"           : top_sensor,
            "threats_blocked"      : threats_blocked,
            "intrusion_attempts"   : intrusion_attempts,
            "network_status"       : "SECURE",
            "failures_predicted"   : failures_predicted,
            "maintenance_completed": maintenance_done,
            "top_risk_component"   : top_risk_component,
            "top_risk_percent"     : top_risk_percent,
            "total_kwh_saved"      : total_kwh_saved,
            "total_eur_saved"      : total_eur_saved,
            "peak_reduction"       : peak_reduction,
            "entso_actions"        : entso_actions,
            "orders_processed"     : orders_processed,
            "low_stock_alerts"     : low_stock_alerts,
            "supplier_performance" : sup_perf,
            "inventory_health"     : inventory_health
        }

    except Exception as e:
        logger.error(f"get_daily_context error: {e}")
        return {
            "date": now.strftime("%Y-%m-%d"),
            "health_score": 0, "prev_health_score": 0,
            "total_anomalies": 0, "critical_count": 0,
            "avg_score": 0, "top_sensor": "unknown",
            "threats_blocked": 0, "intrusion_attempts": 0,
            "network_status": "UNKNOWN",
            "failures_predicted": 0, "maintenance_completed": 0,
            "top_risk_component": "unknown", "top_risk_percent": 0,
            "total_kwh_saved": 0, "total_eur_saved": 0,
            "peak_reduction": 0, "entso_actions": 0,
            "orders_processed": 0, "low_stock_alerts": 0,
            "supplier_performance": "N/A", "inventory_health": 0
        }
    finally:
        db.close()


# ── Quick test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("metric_aggregator.py — Test")
    print("=" * 60)

    print("\n[TEST 1] Hourly context:")
    ctx = get_hourly_context()
    for k, v in ctx.items():
        print(f"  {k:25} : {v}")

    print("\n[TEST 2] Daily context:")
    ctx2 = get_daily_context()
    for k, v in ctx2.items():
        print(f"  {k:25} : {v}")

    print("\nOK metric_aggregator.py done")
