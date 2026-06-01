
"""
CORTEX Phase 2 - API Routes
GET /api/sensors/history      - last 100 readings per sensor
GET /api/sentinel/anomalies   - anomaly log with dual-model scores
GET /api/oracle/predictions   - failure probabilities Machine A/B/C
GET /api/guardian/status      - network security status
GET /api/system/status        - overall health check
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from collections import deque
from datetime import datetime, timezone
from fastapi import APIRouter

router = APIRouter()

# In-memory stores — populated by cortex_master each cycle
sensor_history: dict = {}        # {sensor_id: deque(maxlen=100)}
anomaly_log:    deque = deque(maxlen=50)
oracle_cache:   dict  = {}
guardian_cache: dict  = {}


def push_sensor_reading(sensor_id, value, timestamp, is_anomaly=False, anomaly_score=0.0):
    if sensor_id not in sensor_history:
        sensor_history[sensor_id] = deque(maxlen=100)
    sensor_history[sensor_id].append({
        "timestamp":    timestamp,
        "value":        round(float(value), 4),
        "is_anomaly":   is_anomaly,
        "anomaly_score": round(float(anomaly_score), 4),
    })

def push_anomaly_result(result: dict):
    anomaly_log.append(result)

def update_oracle_cache(result: dict):
    global oracle_cache
    oracle_cache = result

def update_guardian_cache(result: dict):
    global guardian_cache
    guardian_cache = result


@router.get("/api/sensors/history")
async def get_sensor_history(sensor_id: str = None, limit: int = 100):
    if sensor_id:
        data = list(sensor_history.get(sensor_id, []))[-limit:]
        return {"sensor_id": sensor_id, "readings": data, "count": len(data)}
    all_data = {sid: list(readings)[-limit:] for sid, readings in sensor_history.items()}
    return {"sensors": all_data, "count": len(all_data)}


@router.get("/api/sentinel/anomalies")
async def get_sentinel_anomalies(limit: int = 50):
    data = list(anomaly_log)[-limit:]
    flagged = [r for r in data if r.get("status") == "ANOMALY_DETECTED"]
    return {
        "total_cycles":   len(data),
        "total_anomalies": len(flagged),
        "anomaly_rate":   round(len(flagged) / max(len(data), 1), 4),
        "results":        data,
    }


@router.get("/api/oracle/predictions")
async def get_oracle_predictions():
    if not oracle_cache:
        from agents.oracle import run_oracle_cycle
        result = run_oracle_cycle()
        update_oracle_cache(result)
        return result
    return oracle_cache


@router.get("/api/guardian/status")
async def get_guardian_status():
    if not guardian_cache:
        from agents.guardian import run_guardian_cycle
        result = run_guardian_cycle()
        update_guardian_cache(result)
        return result
    return guardian_cache


@router.get("/api/system/status")
async def get_system_status():
    return {
        "status":    "operational",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phase":     2,
        "agents": {
            "SENTINEL": "active",
            "GUARDIAN": "active" if guardian_cache else "initializing",
            "ORACLE":   "active" if oracle_cache   else "initializing",
            "SCRIBE":   "active",
        },
        "data": {
            "sensor_streams":  len(sensor_history),
            "anomaly_records": len(anomaly_log),
        }
    }

# ─────────────────────────────────────────────
# PHASE 3 — ORACLE + OPTIMUS ENDPOINTS
# ─────────────────────────────────────────────

# In-memory caches for Phase 3
forecast_cache:     dict = {}
maintenance_cache:  dict = {}
optimus_cache:      dict = {}

def update_forecast_cache(result: dict):
    global forecast_cache
    forecast_cache = result

def update_maintenance_cache(result: dict):
    global maintenance_cache
    maintenance_cache = result

def update_optimus_cache(result: dict):
    global optimus_cache
    optimus_cache = result

@router.get("/api/oracle/demand-forecast")
async def get_demand_forecast():
    """Returns 24hr Prophet demand predictions with confidence bands."""
    if not forecast_cache:
        from agents.oracle import get_demand_forecast as oracle_forecast
        result = oracle_forecast()
        update_forecast_cache(result)
        return result
    return forecast_cache

@router.get("/api/oracle/maintenance-windows")
async def get_maintenance_windows():
    """Returns top 3 recommended maintenance windows."""
    if not maintenance_cache:
        from agents.oracle import get_maintenance_windows
        result = get_maintenance_windows()
        update_maintenance_cache(result)
        return result
    return maintenance_cache

@router.get("/api/oracle/shap-explanation")
async def get_shap_explanation(machine_id: str = "B"):
    """Returns SHAP feature importance for failure prediction."""
    from agents.oracle import explain_failure, _ensure_trained
    import numpy as np
    _ensure_trained()
    # Use realistic high-stress stats for demonstration
    off = {"A": 0, "B": 1, "C": 2}.get(machine_id.upper(), 1)
    stats = {
        "temp_mean":           65.0 + off * 4 + np.random.normal(0, 1),
        "temp_std":            2.0  + off * 0.5,
        "temp_max":            72.0 + off * 4,
        "vib_mean":            0.5  + off * 0.08,
        "vib_std":             0.05 + off * 0.02,
        "vib_max":             0.65 + off * 0.1,
        "anomaly_count":       off * 2,
        "anomaly_rate":        off * 0.04,
        "combined_score_mean": off * 0.15,
        "combined_score_max":  off * 0.3,
        "cycles_since_last":   max(10, 50 - off * 15),
    }
    return explain_failure(machine_id.upper(), stats)

@router.get("/api/optimus/energy-status")
async def get_energy_status():
    """Returns current energy price, active action, savings this hour."""
    if not optimus_cache:
        from agents.optimus import run_optimus_cycle
        result = run_optimus_cycle()
        update_optimus_cache(result)
    from agents.optimus import get_energy_status as optimus_status
    return optimus_status()

@router.get("/api/optimus/actions-log")
async def get_actions_log(limit: int = 24):
    """Returns last N OPTIMUS decisions with outcomes."""
    from agents.optimus import get_actions_log as optimus_log
    return optimus_log(last_n=limit)
