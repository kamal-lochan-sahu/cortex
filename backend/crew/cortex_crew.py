"""
cortex_crew.py — CORTEX_MASTER Orchestrator
Coordinates SENTINEL and SCRIBE agents in one pipeline.

ARCHITECTURE:
  CORTEX_MASTER (this file)
    └── runs sequentially:
          1. SENTINEL — detect anomaly
          2. SCRIBE   — log and report
          
WHY SEQUENTIAL IN PHASE 1?
  RAM constraint: 1.9GB available.
  Running agents in parallel would exhaust memory.
  Sequential = one agent at a time = safe on low-RAM systems.
  Parallel mode comes in Phase 3 when we optimize memory.
"""

import json
from datetime import datetime, timezone
from agents.sentinel import run_sentinel_direct
from agents.scribe import run_scribe_cycle, _generate_narrative
from database.crud import save_sentinel_log, save_scribe_report
from data.sensor_generator import generate_snapshot


class CortexMaster:
    """
    CORTEX_MASTER — Central orchestrator.
    
    In Phase 1: direct Python orchestration (no LLM).
    In Phase 5: CrewAI hierarchical process with Phi-3-mini.
    
    WHY CLASS NOT FUNCTION?
    State tracking — Master needs to know:
      - how many cycles ran
      - how many anomalies detected
      - last detection timestamp
    A class holds this state cleanly.
    """

    def __init__(self):
        self.cycle_count    = 0
        self.anomaly_count  = 0
        self.last_result    = None
        self.started_at     = datetime.now(timezone.utc).isoformat()

    def run_cycle(self) -> dict:
        """
        Run one complete CORTEX pipeline cycle:
          Step 1 — SENTINEL detects anomaly
          Step 2 — MASTER evaluates result
          Step 3 — SCRIBE logs and reports (always)
          Step 4 — MASTER returns consolidated status

        Returns: full pipeline result dict
        """
        self.cycle_count += 1
        cycle_id = self.cycle_count

        print(f"\n[MASTER] ── Cycle {cycle_id} starting ──")

        # ── Step 1: SENTINEL ───────────────────────────────────────────
        print(f"[MASTER] → Routing to SENTINEL...")
        snapshot = generate_snapshot(anomaly_probability=0.05)
        sentinel_result = run_sentinel_direct()

        print(f"[MASTER] ← SENTINEL returned: {sentinel_result['status']}")

        # ── Step 2: Master evaluation ──────────────────────────────────
        # Priority routing: ANOMALY gets flagged immediately
        # In Phase 3: MASTER will also route to ORACLE for prediction
        if sentinel_result["status"] == "ANOMALY_DETECTED":
            self.anomaly_count += 1
            priority = "HIGH" if sentinel_result["anomaly_score"] < -0.40 else "MEDIUM"
            print(f"[MASTER] ⚠ Anomaly confirmed. Priority: {priority}")
        else:
            priority = "LOW"
            print(f"[MASTER] ✓ No anomaly. Priority: {priority}")

        # ── Step 3: SCRIBE ─────────────────────────────────────────────
        print(f"[MASTER] → Routing to SCRIBE...")
        log = save_sentinel_log(sentinel_result, snapshot)
        narrative = _generate_narrative(sentinel_result)
        report = save_scribe_report(
            content=narrative,
            report_type="cycle",
            sentinel_log_id=log.id
        )
        print(f"[MASTER] ← SCRIBE logged: log_id={log.id}, report_id={report.id}")

        # ── Step 4: Consolidated result ────────────────────────────────
        pipeline_result = {
            "cycle_id":         cycle_id,
            "priority":         priority,
            "sentinel_status":  sentinel_result["status"],
            "anomaly_score":    sentinel_result["anomaly_score"],
            "detection_method": sentinel_result["detection_method"],
            "flagged_sensors":  sentinel_result["flagged_sensors"],
            "summary":          sentinel_result["summary"],
            "log_id":           log.id,
            "report_id":        report.id,
            "timestamp":        sentinel_result["timestamp"],
        }

        self.last_result = pipeline_result
        print(f"[MASTER] ── Cycle {cycle_id} complete ──")
        return pipeline_result

    def get_status(self) -> dict:
        """Return current MASTER status — used by FastAPI /agents endpoint."""
        return {
            "master_status":    "RUNNING",
            "started_at":       self.started_at,
            "cycles_completed": self.cycle_count,
            "anomalies_found":  self.anomaly_count,
            "anomaly_rate":     round(
                self.anomaly_count / self.cycle_count * 100, 1
            ) if self.cycle_count > 0 else 0.0,
            "last_result":      self.last_result,
        }


# ── Singleton instance ────────────────────────────────────────────────────────
# One master instance shared across FastAPI + scheduler.
# WHY SINGLETON? APScheduler and FastAPI both need the same
# cycle_count and anomaly_count — shared state.

_master_instance = None

def get_master() -> CortexMaster:
    global _master_instance
    if _master_instance is None:
        _master_instance = CortexMaster()
    return _master_instance


if __name__ == "__main__":
    print("=" * 60)
    print("CORTEX_MASTER — Orchestrator Test")
    print("=" * 60)

    master = CortexMaster()

    print("\n[TEST] Running 5 pipeline cycles:")
    for i in range(5):
        result = master.run_cycle()
        print(f"\n  Result: priority={result['priority']} | "
              f"status={result['sentinel_status']} | "
              f"log_id={result['log_id']}")
        print(f"  Narrative preview: {result['summary'][:60]}...")

    print("\n[STATUS] Master status after 5 cycles:")
    status = master.get_status()
    print(f"  Cycles completed : {status['cycles_completed']}")
    print(f"  Anomalies found  : {status['anomalies_found']}")
    print(f"  Anomaly rate     : {status['anomaly_rate']}%")

    print("\nOK cortex_crew.py working correctly")
