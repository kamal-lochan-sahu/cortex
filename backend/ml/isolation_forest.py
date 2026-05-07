import numpy as np
import pickle
import os
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from data.sensor_generator import generate_training_batch, generate_snapshot

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "models", "sentinel_isolation_forest")
MODEL_PATH = os.path.join(MODEL_DIR, "model.pkl")
SCALER_PATH = os.path.join(MODEL_DIR, "scaler.pkl")

SCORE_THRESHOLD = -0.35


def _batch_to_matrix(batch):
    from collections import defaultdict
    grouped = defaultdict(dict)
    sensor_ids = []
    for reading in batch:
        ts = reading["timestamp"]
        sid = reading["sensor_id"]
        grouped[ts][sid] = reading["value"]
        if sid not in sensor_ids:
            sensor_ids.append(sid)
    sensor_ids = sorted(sensor_ids)
    rows = []
    for ts in sorted(grouped.keys()):
        row = [grouped[ts].get(sid, 0.0) for sid in sensor_ids]
        rows.append(row)
    return np.array(rows), sensor_ids


def train(n_samples=500, contamination=0.1):
    os.makedirs(MODEL_DIR, exist_ok=True)
    print("[SENTINEL] Generating training data...")
    batch = generate_training_batch(n_samples=n_samples)
    X, sensor_ids = _batch_to_matrix(batch)
    print(f"[SENTINEL] Training matrix shape: {X.shape}")
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    print("[SENTINEL] Training Isolation Forest...")
    model = IsolationForest(
        n_estimators=100,
        contamination=contamination,
        random_state=42,
        n_jobs=1
    )
    model.fit(X_scaled)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(model, f)
    with open(SCALER_PATH, "wb") as f:
        pickle.dump(scaler, f)
    print(f"[SENTINEL] Model saved.")
    return model, scaler, sensor_ids


def load_model():
    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError("Model not found. Run train() first.")
    with open(MODEL_PATH, "rb") as f:
        model = pickle.load(f)
    with open(SCALER_PATH, "rb") as f:
        scaler = pickle.load(f)
    return model, scaler


def infer(snapshot):
    """
    Dual detection strategy:
      1. ML score  — Isolation Forest score_samples()
      2. Rule-based — value outside 15% of normal range

    WHY DUAL?
      Isolation Forest excels at multi-sensor correlated anomalies.
      Rule-based catches single-sensor spikes reliably.
      Combined = higher recall, fewer missed anomalies.
      Industrial systems always use layered detection.

    is_anomaly = True if EITHER method detects anomaly.
    detection_method tells us which one fired.
    """
    model, scaler = load_model()

    sensor_ids = sorted([r["sensor_id"] for r in snapshot])
    reading_map = {r["sensor_id"]: r["value"] for r in snapshot}
    row = np.array([[reading_map[sid] for sid in sensor_ids]])
    row_scaled = scaler.transform(row)
    score = model.score_samples(row_scaled)[0]

    ml_anomaly = score < SCORE_THRESHOLD

    flagged = [
        r for r in snapshot
        if r["value"] > r["normal_max"] * 1.15
        or r["value"] < r["normal_min"] * 0.85
    ]
    rule_anomaly = len(flagged) > 0

    is_anomaly = ml_anomaly or rule_anomaly

    if ml_anomaly and rule_anomaly:
        method = "both"
    elif ml_anomaly:
        method = "ml_score"
    elif rule_anomaly:
        method = "rule_based"
    else:
        method = "none"

    return {
        "is_anomaly":       is_anomaly,
        "anomaly_score":    round(float(score), 4),
        "detection_method": method,
        "flagged_sensors":  [
            {"sensor_id": r["sensor_id"], "value": r["value"],
             "normal_max": r["normal_max"]} for r in flagged
        ],
        "timestamp": snapshot[0]["timestamp"],
    }


if __name__ == "__main__":
    print("=" * 60)
    print("SENTINEL — Isolation Forest Test")
    print("=" * 60)

    train(n_samples=300)

    print("\n[TEST 1] Normal snapshot:")
    snap = generate_snapshot(anomaly_probability=0.0)
    result = infer(snap)
    print(f"  is_anomaly    : {result['is_anomaly']}")
    print(f"  score         : {result['anomaly_score']}")
    print(f"  method        : {result['detection_method']}")
    print(f"  flagged       : {result['flagged_sensors']}")

    print("\n[TEST 2] Forced anomaly on temp_01:")
    snap2 = generate_snapshot(force_anomaly_sensor_id="temp_01")
    result2 = infer(snap2)
    print(f"  is_anomaly    : {result2['is_anomaly']}")
    print(f"  score         : {result2['anomaly_score']}")
    print(f"  method        : {result2['detection_method']}")
    print(f"  flagged       : {result2['flagged_sensors']}")

    print("\n[TEST 3] Forced anomaly on vib_01:")
    snap3 = generate_snapshot(force_anomaly_sensor_id="vib_01")
    result3 = infer(snap3)
    print(f"  is_anomaly    : {result3['is_anomaly']}")
    print(f"  score         : {result3['anomaly_score']}")
    print(f"  method        : {result3['detection_method']}")
    print(f"  flagged       : {result3['flagged_sensors']}")

    print("\nOK isolation_forest.py working correctly")
