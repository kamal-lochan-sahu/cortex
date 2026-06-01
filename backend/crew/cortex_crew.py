"""
cortex_crew.py — CORTEX_MASTER Orchestrator (Phase 3)
Coordinates all 4 active agents in priority hierarchy.

PRIORITY HIERARCHY:
  P0: GUARDIAN  — security threat  → ALL STOP
  P1: SENTINEL  — anomaly detected → immediate
  P2: ORACLE    — imminent failure → urgent
  P3: OPTIMUS   — optimization     → routine
  P4: SCRIBE    — reporting        → background

CONFLICT RESOLUTION:
  If OPTIMUS says REDUCE_20
  AND ORACLE says high production demand
  → MASTER: ORACLE takes priority
  → Conflict logged to DB
"""

import json
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone
from agents.sentinel import run_sentinel_direct
from agents.scribe import run_scribe_cycle, _generate_narrative
from agents.oracle import run_oracle_cycle, get_demand_forecast
from agents.optimus import run_optimus_cycle, get_energy_status
from database.crud import save_sentinel_log, save_scribe_report
from data.sensor_generator import generate_snapshot
from api.routes import (
    push_sensor_reading, push_anomaly_result,
    update_oracle_cache, update_guardian_cache,
    update_forecast_cache, update_maintenance_cache,
    update_optimus_cache,
)

# Conflict log — in memory, last 50
_conflict_log: list[dict] = []

def _log_conflict(reason: str, winner: str, loser: str, detail: str):
    global _conflict_log
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason":    reason,
        "winner":    winner,
        "loser":     loser,
        "detail":    detail,
    }
    _conflict_log.append(record)
    if len(_conflict_log) > 50:
        _conflict_log.pop(0)
    print(f"[MASTER] ⚡ CONFLICT: {loser} overridden by {winner} — {reason}")
    return record


class CortexMaster:
    def __init__(self):
        self.cycle_count       = 0
        self.anomaly_count     = 0
        self.conflict_count    = 0
        self.last_result       = None
        self.started_at        = datetime.now(timezone.utc).isoformat()
        # ORACLE runs every 6 cycles (~1 min), OPTIMUS every 2 cycles (~20s)
        self._oracle_interval  = 6
        self._optimus_interval = 2

    def run_cycle(self) -> dict:
        self.cycle_count += 1
        cycle_id = self.cycle_count
        print(f"\n[MASTER] ── Cycle {cycle_id} starting ──")

        # ── P1: SENTINEL ──────────────────────────────────────────────
        print(f"[MASTER] → P1: SENTINEL")
        snapshot       = generate_snapshot(anomaly_probability=0.05)
        sentinel_result = run_sentinel_direct()
        print(f"[MASTER] ← SENTINEL: {sentinel_result['status']}")

        if sentinel_result["status"] == "ANOMALY_DETECTED":
            self.anomaly_count += 1
            score    = sentinel_result.get("combined_score",
                       sentinel_result.get("anomaly_score", 0))
            priority = "HIGH" if score > 0.4 else "MEDIUM"
        else:
            priority = "LOW"

        # Push to API cache
        push_anomaly_result(sentinel_result)
        for item in snapshot:
            push_sensor_reading(
                item["sensor_id"], item["value"],
                item["timestamp"],
                item.get("is_anomaly", False),
                0.0,
            )

        # ── P2: ORACLE — every 6 cycles ───────────────────────────────
        oracle_result   = None
        forecast_result = None
        if cycle_id % self._oracle_interval == 0:
            print(f"[MASTER] → P2: ORACLE")
            anomaly_history = list(sentinel_result.get("flagged_sensors", []))
            oracle_result   = run_oracle_cycle(anomaly_history)
            forecast_result = get_demand_forecast()
            update_oracle_cache(oracle_result)
            update_forecast_cache(forecast_result)
            update_maintenance_cache(oracle_result.get("maintenance", {}))
            print(f"[MASTER] ← ORACLE: predictions + forecast ready")

        # ── P3: OPTIMUS — every 2 cycles ──────────────────────────────
        optimus_result = None
        conflict       = None
        if cycle_id % self._optimus_interval == 0:
            print(f"[MASTER] → P3: OPTIMUS")

            # Pass current demand to OPTIMUS if ORACLE ran
            current_demand = None
            if forecast_result:
                now_hour       = datetime.now(timezone.utc).hour
                fc_list        = forecast_result.get("forecast", [])
                current_hour_fc = next(
                    (p for p in fc_list if p["hour"] == 0), None
                )
                if current_hour_fc:
                    current_demand = current_hour_fc["yhat"]

            optimus_result = run_optimus_cycle(current_demand=current_demand)
            update_optimus_cache(optimus_result)
            print(f"[MASTER] ← OPTIMUS: action={optimus_result['action']} "
                  f"conf={optimus_result['confidence']:.2f}")

            # ── CONFLICT RESOLUTION ───────────────────────────────────
            # Rule: if OPTIMUS wants to reduce production
            # AND ORACLE shows high demand → ORACLE wins
            if oracle_result and optimus_result:
                optimus_action  = optimus_result["action"]
                reduce_actions  = {"REDUCE_10", "REDUCE_20", "SHIFT_HEAVY"}

                # Get max predicted demand in next 6h
                fc_list     = forecast_result.get("forecast", []) if forecast_result else []
                next_6h     = [p["yhat"] for p in fc_list[:6]]
                peak_demand = max(next_6h) if next_6h else 0

                if optimus_action in reduce_actions and peak_demand > 75:
                    conflict = _log_conflict(
                        reason=f"OPTIMUS={optimus_action} conflicts with "
                               f"peak demand={peak_demand:.1f} units",
                        winner="ORACLE",
                        loser="OPTIMUS",
                        detail=f"Production demand too high to reduce. "
                               f"OPTIMUS action overridden → NORMAL",
                    )
                    self.conflict_count += 1
                    # Override OPTIMUS action
                    optimus_result["action"]       = "NORMAL"
                    optimus_result["auto_applied"] = False
                    optimus_result["conflict_override"] = True

        # ── P4: SCRIBE — always ───────────────────────────────────────
        print(f"[MASTER] → P4: SCRIBE")
        log       = save_sentinel_log(sentinel_result, snapshot)
        narrative = _generate_narrative(sentinel_result)
        report    = save_scribe_report(
            content=narrative,
            report_type="cycle",
            sentinel_log_id=log.id
        )
        print(f"[MASTER] ← SCRIBE: log_id={log.id}")

        # ── Consolidated result ────────────────────────────────────────
        pipeline_result = {
            "cycle_id":         cycle_id,
            "priority":         priority,
            "sentinel_status":  sentinel_result["status"],
            "anomaly_score":    sentinel_result.get("combined_score",
                                sentinel_result.get("anomaly_score", 0.0)),
            "detection_method": sentinel_result["detection_method"],
            "flagged_sensors":  sentinel_result["flagged_sensors"],
            "summary":          sentinel_result["summary"],
            "log_id":           log.id,
            "report_id":        report.id,
            "timestamp":        sentinel_result["timestamp"],
            "oracle_ran":       oracle_result is not None,
            "optimus_ran":      optimus_result is not None,
            "conflict":         conflict,
        }

        self.last_result = pipeline_result
        print(f"[MASTER] ── Cycle {cycle_id} complete ──")
        return pipeline_result

    def get_status(self) -> dict:
        return {
            "master_status":    "RUNNING",
            "started_at":       self.started_at,
            "cycles_completed": self.cycle_count,
            "anomalies_found":  self.anomaly_count,
            "conflict_count":   self.conflict_count,
            "anomaly_rate":     round(
                self.anomaly_count / self.cycle_count * 100, 1
            ) if self.cycle_count > 0 else 0.0,
            "last_result":      self.last_result,
            "recent_conflicts": _conflict_log[-5:],
        }


# ── Singleton ─────────────────────────────────────────────────────────────────
_master_instance = None

def get_master() -> CortexMaster:
    global _master_instance
    if _master_instance is None:
        _master_instance = CortexMaster()
    return _master_instance


if __name__ == "__main__":
    print("=" * 60)
    print("CORTEX_MASTER Phase 3 — Orchestrator Test")
    print("=" * 60)

    master = CortexMaster()
    print("\n[TEST] Running 6 pipeline cycles:")
    for i in range(6):
        result = master.run_cycle()
        print(f"\n  Cycle {result['cycle_id']}: priority={result['priority']} "
              f"oracle={result['oracle_ran']} "
              f"optimus={result['optimus_ran']} "
              f"conflict={result['conflict'] is not None}")

    print("\n[STATUS]")
    status = master.get_status()
    print(f"  Cycles    : {status['cycles_completed']}")
    print(f"  Anomalies : {status['anomalies_found']}")
    print(f"  Conflicts : {status['conflict_count']}")
    print(f"  Conflicts log: {status['recent_conflicts']}")
    print("\nCORTEX_MASTER Phase 3 working.")
