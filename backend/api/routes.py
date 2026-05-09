
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
