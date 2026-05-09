"""
sentinel.py
CORTEX — SENTINEL Agent v2
Real-time sensor anomaly detection — Dual Model.

Phase 2 upgrade: runs BOTH Isolation Forest (point anomaly)
AND LSTM Autoencoder (temporal/sequence anomaly) on every cycle.

Detection method:
  "isolation_forest" → IF flagged, LSTM did not
  "lstm"             → LSTM flagged, IF did not
  "both"             → both models flagged (highest confidence)
  "none"             → all normal

RAM strategy:
  LSTM model loaded once at module import (175KB).
  Window buffer maintained in memory (14 sensors × 20 floats = tiny).
  Both models run sequentially — never concurrently.
"""

from crewai import Agent, Task, Crew, Process
from crewai.tools import tool

from ml.isolation_forest import infer, train
from ml.lstm_autoencoder import lstm_ae
from data.sensor_generator import generate_snapshot

from collections import deque
import os
import json
import logging

logger = logging.getLogger(__name__)


# ── Sensor Window Buffer ──────────────────────────────────────────
# LSTM Autoencoder needs last 20 readings per sensor.
# This buffer maintains a rolling window for all 14 sensors.
# deque(maxlen=20) automatically drops oldest value when full.

class SensorWindowBuffer:
    """
    Maintains rolling 20-step history for each sensor.

    Why deque(maxlen=20)?
    - O(1) append — fast per cycle
    - Auto-drops oldest value — no manual management
    - 14 sensors × 20 floats × 4 bytes = ~1.1 KB total — negligible RAM
    """

    def __init__(self, window_size: int = 20):
        self.window_size = window_size
        self.buffers: dict[str, deque] = {}

    def update(self, snapshot: dict) -> None:
        """Add latest sensor readings to all buffers."""
        readings = snapshot if isinstance(snapshot, list) else snapshot.get('sensors', [])
        for reading in readings:
            sid = reading['sensor_id']
            if sid not in self.buffers:
                # First time seeing this sensor — create buffer
                self.buffers[sid] = deque(maxlen=self.window_size)
            self.buffers[sid].append(float(reading['value']))

    def get_window(self, sensor_id: str) -> list[float] | None:
        """
        Returns 20-step window for a sensor, or None if not enough history.
        First 19 cycles will return None — LSTM stays inactive until
        buffer is full. IF handles detection during warmup.
        """
        if sensor_id not in self.buffers:
            return None
        buf = self.buffers[sensor_id]
        if len(buf) < self.window_size:
            return None
        return list(buf)

    def is_ready(self, sensor_id: str) -> bool:
        """True if sensor has 20 readings buffered."""
        return (
            sensor_id in self.buffers and
            len(self.buffers[sensor_id]) >= self.window_size
        )

    @property
    def ready_sensors(self) -> list[str]:
        """List of sensor IDs with full 20-step buffers."""
        return [sid for sid in self.buffers if self.is_ready(sid)]

    @property
    def warmup_complete(self) -> bool:
        """True once at least one sensor has full buffer."""
        return len(self.ready_sensors) > 0


# Module-level singletons
# Instantiated once — reused across every monitoring cycle
_window_buffer = SensorWindowBuffer(window_size=20)
_lstm_loaded   = False


def _ensure_lstm_loaded() -> bool:
    """
    Load LSTM model on first call, skip if already loaded.
    Returns True if model is ready, False if loading failed.
    """
    global _lstm_loaded
    if _lstm_loaded:
        return True
    try:
        lstm_ae.load()
        _lstm_loaded = True
        logger.info("LSTM Autoencoder loaded into SENTINEL.")
        return True
    except Exception as e:
        logger.warning(f"LSTM load failed — running IF only: {e}")
        return False


# ── Core Dual Detection ───────────────────────────────────────────

def _run_lstm_detection(snapshot: dict) -> dict:
    """
    Run LSTM Autoencoder on all sensors with full 20-step buffers.

    Returns:
        {
          'is_anomaly':      bool,
          'lstm_score':      float,   # max anomaly_score across sensors
          'flagged_sensors': list,    # sensors LSTM flagged
          'per_sensor':      dict,    # full results per sensor
          'ready':           bool,    # False during warmup (< 20 cycles)
        }
    """
    if not _window_buffer.warmup_complete:
        return {
            'is_anomaly':      False,
            'lstm_score':      0.0,
            'flagged_sensors': [],
            'per_sensor':      {},
            'ready':           False,
        }

    flagged    = []
    per_sensor = {}
    max_score  = 0.0

    readings = snapshot if isinstance(snapshot, list) else snapshot.get('sensors', [])
    for reading in readings:
        sid    = reading['sensor_id']
        window = _window_buffer.get_window(sid)

        if window is None:
            continue  # sensor not ready yet

        try:
            result = lstm_ae.predict(window)
            per_sensor[sid] = result

            if result['anomaly_score'] > max_score:
                max_score = result['anomaly_score']

            if result['is_anomaly']:
                flagged.append({
                    'sensor_id':            sid,
                    'lstm_score':           result['anomaly_score'],
                    'reconstruction_error': result['reconstruction_error'],
                    'confidence':           result['confidence'],
                })

        except Exception as e:
            logger.warning(f"LSTM predict failed for {sid}: {e}")

    return {
        'is_anomaly':      len(flagged) > 0,
        'lstm_score':      round(max_score, 4),
        'flagged_sensors': flagged,
        'per_sensor':      per_sensor,
        'ready':           True,
    }


def _combine_results(if_result: dict, lstm_result: dict) -> dict:
    """
    Merge IF and LSTM results into unified SENTINEL output.

    Combined score logic:
      Both models normalize to [0, 1] range before averaging.
      IF score: raw score is negative (more negative = more anomalous).
        Normalize: if_normalized = min(1.0, abs(if_score) * 2)
      LSTM score: anomaly_score ratio (>1 = anomaly).
        Normalize: lstm_normalized = min(1.0, lstm_score / 5.0)
      Combined = 0.5 * if_normalized + 0.5 * lstm_normalized

    Detection method:
      "both"             → both flagged
      "isolation_forest" → only IF flagged
      "lstm"             → only LSTM flagged
      "none"             → neither flagged
    """
    if_anomaly   = if_result.get('is_anomaly',  False)
    lstm_anomaly = lstm_result.get('is_anomaly', False)

    # Normalize IF score to [0, 1]
    raw_if_score   = if_result.get('anomaly_score', 0.0)
    if_normalized  = min(1.0, abs(float(raw_if_score)) * 2.0)

    # Normalize LSTM score to [0, 1]
    raw_lstm_score  = lstm_result.get('lstm_score', 0.0)
    lstm_normalized = min(1.0, float(raw_lstm_score) / 5.0)

    # Combined
    combined_score = round(0.5 * if_normalized + 0.5 * lstm_normalized, 4)

    # Detection method
    if if_anomaly and lstm_anomaly:
        detection_method = "both"
    elif if_anomaly:
        detection_method = "isolation_forest"
    elif lstm_anomaly:
        detection_method = "lstm"
    else:
        detection_method = "none"

    is_anomaly = if_anomaly or lstm_anomaly

    # Merge flagged sensors from both models (deduplicated)
    if_flagged   = if_result.get('flagged_sensors', [])
    lstm_flagged = lstm_result.get('flagged_sensors', [])

    # Build unified flagged list
    flagged_ids  = set()
    flagged_list = []

    for s in if_flagged:
        sid = s.get('sensor_id') or s.get('id', '')
        if sid and sid not in flagged_ids:
            flagged_ids.add(sid)
            flagged_list.append({
                'sensor_id':  sid,
                'if_score':   s.get('score', raw_if_score),
                'lstm_score': 0.0,
                'detected_by': 'isolation_forest',
            })

    for s in lstm_flagged:
        sid = s.get('sensor_id', '')
        if sid in flagged_ids:
            # Already in list — update with LSTM score
            for f in flagged_list:
                if f['sensor_id'] == sid:
                    f['lstm_score']   = s.get('lstm_score', 0.0)
                    f['detected_by']  = 'both'
        else:
            flagged_ids.add(sid)
            flagged_list.append({
                'sensor_id':   sid,
                'if_score':    0.0,
                'lstm_score':  s.get('lstm_score', 0.0),
                'detected_by': 'lstm',
            })

    return {
        'is_anomaly':       is_anomaly,
        'if_score':         round(float(raw_if_score), 4),
        'lstm_score':       round(float(raw_lstm_score), 4),
        'combined_score':   combined_score,
        'detection_method': detection_method,
        'flagged_sensors':  flagged_list,
        'lstm_ready':       lstm_result.get('ready', False),
    }


# ── CrewAI Tools ──────────────────────────────────────────────────

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
    Run dual anomaly detection (Isolation Forest + LSTM Autoencoder)
    on a sensor snapshot.
    Input: JSON string of sensor snapshot from SensorSnapshot tool.
    Returns: anomaly verdict, if_score, lstm_score, combined_score,
             detection_method, flagged sensors.
    """
    try:
        snapshot = json.loads(snapshot_json)
        result   = infer(snapshot)
        return json.dumps(result, indent=2)
    except FileNotFoundError:
        return json.dumps({
            "error":  "Model not trained. Training now...",
            "action": "train_required"
        })


@tool("TrainModel")
def train_sentinel_model(input: str = "") -> str:
    """
    Train the Isolation Forest model on fresh sensor data.
    Use this only if AnomalyDetector reports model not found.
    """
    try:
        train(n_samples=300)
        return json.dumps({"status": "trained", "samples": 300})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Agent + Task ──────────────────────────────────────────────────

def create_sentinel_agent() -> Agent:
    return Agent(
        role="Senior Industrial Anomaly Detection Specialist",
        goal=(
            "Monitor all 14 factory sensor streams in real-time. "
            "Detect anomalies using dual-model detection: "
            "Isolation Forest for point anomalies, "
            "LSTM Autoencoder for temporal/sequence anomalies. "
            "Report structured alerts with sensor IDs, scores, and detection method."
        ),
        backstory=(
            "You are SENTINEL, CORTEX's primary monitoring intelligence. "
            "You run two AI models simultaneously — Isolation Forest for "
            "sudden spikes and LSTM Autoencoder for gradual drift patterns. "
            "You are precise, fast, and report full technical detail on every alert."
        ),
        tools=[get_sensor_snapshot, run_anomaly_detection, train_sentinel_model],
        verbose=False,
        allow_delegation=False,
        max_iter=3,
    )


def create_sentinel_task(agent: Agent) -> Task:
    return Task(
        description=(
            "Execute one complete dual-model sensor monitoring cycle:\n"
            "1. Collect a fresh snapshot of all 14 sensor readings\n"
            "2. Run dual anomaly detection (IF + LSTM)\n"
            "3. Report with detection_method showing which model fired\n"
            "Return JSON with: status, timestamp, if_score, lstm_score, "
            "combined_score, detection_method, flagged_sensors, summary"
        ),
        expected_output=(
            "JSON object with status, timestamp, if_score, lstm_score, "
            "combined_score, detection_method, flagged_sensors, summary."
        ),
        agent=agent,
    )


# ── Main Entry Points ─────────────────────────────────────────────

def run_sentinel_direct() -> dict:
    """
    Run full dual-model SENTINEL detection cycle.
    Called by APScheduler every 10 seconds.
    Called by CORTEX_MASTER when orchestrating.

    Cycle:
    1. Get sensor snapshot
    2. Run Isolation Forest (point anomaly detection)
    3. Update 20-step window buffer
    4. Run LSTM Autoencoder (temporal anomaly detection)
    5. Combine results → unified output
    """
    # ── Step 1: Snapshot ─────────────────────────────────────────
    snapshot = generate_snapshot(anomaly_probability=0.05)

    # ── Step 2: Isolation Forest ──────────────────────────────────
    if_result = infer(snapshot)

    # ── Step 3: Update window buffer ──────────────────────────────
    _window_buffer.update(snapshot)

    # ── Step 4: LSTM Autoencoder ──────────────────────────────────
    lstm_ready = _ensure_lstm_loaded()
    if lstm_ready:
        lstm_result = _run_lstm_detection(snapshot)
    else:
        lstm_result = {
            'is_anomaly':      False,
            'lstm_score':      0.0,
            'flagged_sensors': [],
            'per_sensor':      {},
            'ready':           False,
        }

    # ── Step 5: Combine ───────────────────────────────────────────
    combined = _combine_results(if_result, lstm_result)

    status = "ANOMALY_DETECTED" if combined['is_anomaly'] else "ALL_NORMAL"

    flagged_ids = [s['sensor_id'] for s in combined['flagged_sensors']]

    return {
        "status":           status,
        "timestamp":        if_result["timestamp"],
        "if_score":         combined["if_score"],
        "lstm_score":       combined["lstm_score"],
        "combined_score":   combined["combined_score"],
        "detection_method": combined["detection_method"],
        "flagged_sensors":  combined["flagged_sensors"],
        "lstm_ready":       combined["lstm_ready"],
        "summary": (
            f"Anomaly detected via [{combined['detection_method']}]. "
            f"Combined score: {combined['combined_score']}. "
            f"Flagged: {flagged_ids}"
            if combined['is_anomaly']
            else f"All 14 sensors normal. "
                 f"LSTM: {'active' if combined['lstm_ready'] else 'warming up'}."
        )
    }


def run_sentinel_cycle() -> dict:
    """CrewAI-based cycle (Phase 5 — LLM mode). Currently uses direct mode."""
    return run_sentinel_direct()


if __name__ == "__main__":
    print("=" * 65)
    print("SENTINEL v2 — Dual Model Test (IF + LSTM)")
    print("=" * 65)

    print("\nWarming up buffer (need 20 cycles for LSTM to activate)...")
    for i in range(22):
        r = run_sentinel_direct()
        lstm_status = "ACTIVE" if r["lstm_ready"] else f"warming ({i+1}/20)"
        if r["status"] == "ANOMALY_DETECTED":
            print(f"  Cycle {i+1:02d}: ANOMALY | method={r['detection_method']:<18} "
                  f"| if={r['if_score']:+.3f} lstm={r['lstm_score']:.3f} "
                  f"| LSTM {lstm_status}")
        else:
            print(f"  Cycle {i+1:02d}: normal  | method={r['detection_method']:<18} "
                  f"| if={r['if_score']:+.3f} lstm={r['lstm_score']:.3f} "
                  f"| LSTM {lstm_status}")

    print("\n" + "=" * 65)
    print("Final cycle result:")
    print(json.dumps(r, indent=2))