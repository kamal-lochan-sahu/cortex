"""
sentinel.py
CORTEX — SENTINEL Agent
Real-time sensor anomaly detection using CrewAI.

SENTINEL is the first line of defense in CORTEX.
It continuously monitors 14 industrial sensor streams,
detects anomalies using dual detection (ML + rule-based),
and reports structured alerts to CORTEX_MASTER.
"""

from crewai import Agent, Task, Crew, Process
from crewai.tools import tool

from ml.isolation_forest import infer, train
from data.sensor_generator import generate_snapshot

import os
import json


# ── Tool Definitions ──────────────────────────────────────────────────────────
# CrewAI tools are Python functions decorated with @tool.
# The agent decides WHEN and HOW to use them based on its goal.
# Tool docstring = what the agent "knows" about the tool.

@tool("SensorSnapshot")
def get_sensor_snapshot(input: str = "") -> str:
    """
    Collect a live snapshot of all 14 industrial sensors.
    Returns current readings with normal range boundaries.
    Use this first to get fresh sensor data.
    """
    snapshot = generate_snapshot(anomaly_probability=0.05)
    return json.dumps(snapshot, indent=2)


@tool("AnomalyDetector")
def run_anomaly_detection(snapshot_json: str) -> str:
    """
    Run anomaly detection on a sensor snapshot.
    Input: JSON string of sensor snapshot from SensorSnapshot tool.
    Returns: anomaly verdict, score, detection method, flagged sensors.
    Use this after collecting sensor data.
    """
    try:
        snapshot = json.loads(snapshot_json)
        result = infer(snapshot)
        return json.dumps(result, indent=2)
    except FileNotFoundError:
        return json.dumps({
            "error": "Model not trained. Training now...",
            "action": "train_required"
        })


@tool("TrainModel")
def train_sentinel_model(input: str = "") -> str:
    """
    Train the Isolation Forest model on fresh sensor data.
    Use this only if AnomalyDetector reports model not found.
    Training takes 10-15 seconds.
    """
    try:
        train(n_samples=300)
        return json.dumps({"status": "trained", "samples": 300})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Agent Definition ──────────────────────────────────────────────────────────

def create_sentinel_agent() -> Agent:
    """
    Create the SENTINEL CrewAI agent.

    WHY THESE SPECIFIC ROLE/GOAL/BACKSTORY?
    CrewAI uses these as the system prompt for the LLM.
    More specific = better reasoning quality.
    Industrial language = relevant outputs for CORTEX domain.
    """
    return Agent(
        role="Senior Industrial Anomaly Detection Specialist",
        goal=(
            "Monitor all 14 factory sensor streams in real-time. "
            "Detect anomalies immediately using sensor data analysis. "
            "Provide structured alerts with sensor IDs, values, and severity."
        ),
        backstory=(
            "You are SENTINEL, CORTEX's primary monitoring intelligence. "
            "You have 20 years of experience in industrial sensor analysis "
            "for automotive and manufacturing plants. "
            "You are precise, fast, and never miss a critical anomaly. "
            "When you detect an anomaly, you report it with full technical detail."
        ),
        tools=[get_sensor_snapshot, run_anomaly_detection, train_sentinel_model],
        verbose=False,
        allow_delegation=False,
        max_iter=3,
    )


# ── Task Definition ───────────────────────────────────────────────────────────

def create_sentinel_task(agent: Agent) -> Task:
    """
    Define what SENTINEL must do in one monitoring cycle.

    WHY STRUCTURED OUTPUT?
    SCRIBE agent will parse this output to log to PostgreSQL.
    CORTEX_MASTER will parse this to route alerts.
    Consistent JSON structure = reliable inter-agent communication.
    """
    return Task(
        description=(
            "Execute one complete sensor monitoring cycle:\n"
            "1. Collect a fresh snapshot of all 14 sensor readings\n"
            "2. Run anomaly detection on the snapshot\n"
            "3. If anomaly detected: report full details\n"
            "4. If no anomaly: confirm all systems normal\n"
            "Return a structured JSON report with these fields:\n"
            "  - status: 'ANOMALY_DETECTED' or 'ALL_NORMAL'\n"
            "  - timestamp: ISO timestamp\n"
            "  - anomaly_score: float\n"
            "  - detection_method: string\n"
            "  - flagged_sensors: list\n"
            "  - summary: one sentence description"
        ),
        expected_output=(
            "A JSON object with status, timestamp, anomaly_score, "
            "detection_method, flagged_sensors, and summary fields."
        ),
        agent=agent,
    )


# ── Run One Cycle ─────────────────────────────────────────────────────────────

def run_sentinel_cycle() -> dict:
    """
    Run one complete SENTINEL monitoring cycle.
    Called by APScheduler every 10 seconds in production.
    Called by CORTEX_MASTER when orchestrating agents.

    Returns dict with detection results.
    """
    agent = create_sentinel_agent()
    task = create_sentinel_task(agent)

    crew = Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=False,
    )

    result = crew.kickoff()

    raw = str(result)
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(raw[start:end])
    except json.JSONDecodeError:
        pass

    return {
        "status": "PARSE_ERROR",
        "raw_output": raw,
        "timestamp": __import__("datetime").datetime.utcnow().isoformat()
    }


# ── Direct Detection (no LLM) ─────────────────────────────────────────────────

def run_sentinel_direct() -> dict:
    """
    Run SENTINEL detection directly without LLM reasoning.
    Faster, deterministic, used when LLM not configured.
    This is what Phase 1 uses — LLM added in Phase 5.

    WHY DIRECT MODE?
    Phase 1 has no LLM (Phi-3-mini comes in Phase 5).
    Direct mode gives us the full pipeline working
    without waiting for LLM setup.
    """
    snapshot = generate_snapshot(anomaly_probability=0.05)
    result = infer(snapshot)

    status = "ANOMALY_DETECTED" if result["is_anomaly"] else "ALL_NORMAL"

    return {
        "status":           status,
        "timestamp":        result["timestamp"],
        "anomaly_score":    result["anomaly_score"],
        "detection_method": result["detection_method"],
        "flagged_sensors":  result["flagged_sensors"],
        "summary": (
            f"Anomaly detected via {result['detection_method']}. "
            f"Flagged: {[s['sensor_id'] for s in result['flagged_sensors']]}"
            if result["is_anomaly"]
            else "All 14 sensors operating within normal parameters."
        )
    }


if __name__ == "__main__":
    print("=" * 60)
    print("SENTINEL Agent — Direct Mode Test")
    print("=" * 60)

    print("\n[TEST 1] Normal cycle:")
    result = run_sentinel_direct()
    print(f"  status         : {result['status']}")
    print(f"  anomaly_score  : {result['anomaly_score']}")
    print(f"  method         : {result['detection_method']}")
    print(f"  summary        : {result['summary']}")

    print("\n[TEST 2] 10 rapid cycles (shows live monitoring):")
    anomaly_count = 0
    for i in range(10):
        r = run_sentinel_direct()
        if r["status"] == "ANOMALY_DETECTED":
            anomaly_count += 1
            print(f"  Cycle {i+1:02d}: ANOMALY — {r['summary']}")
        else:
            print(f"  Cycle {i+1:02d}: normal")

    print(f"\n  Anomalies in 10 cycles: {anomaly_count}/10")
    print("\nOK sentinel.py working correctly")
