
"""
CORTEX - GUARDIAN Agent (Phase 2)
Network security anomaly detection.
Phase 2: Lightweight IF on synthetic network features.
Phase 3: Full UNSW-NB15 dataset training.
"""
import json
import numpy as np
from datetime import datetime, timezone
from sklearn.ensemble import IsolationForest

_model = None
_is_trained = False

def _ensure_trained():
    global _model, _is_trained
    if _is_trained:
        return
    np.random.seed(42)
    n = 2000
    X = np.column_stack([
        np.random.normal(100, 15, n),
        np.random.normal(0.35, 0.08, n),
        np.random.normal(0.02, 0.005, n),
        np.random.normal(50, 10, n),
        np.random.normal(12, 3, n),
        np.random.normal(20, 5, n),
    ])
    X = np.clip(X, 0, None)
    _model = IsolationForest(n_estimators=100, contamination=0.05, random_state=42)
    _model.fit(X)
    _is_trained = True


def _snapshot(anomaly_prob=0.08):
    np.random.seed(None)
    is_attack = np.random.random() < anomaly_prob
    if is_attack:
        attack_type = np.random.choice(["ddos", "port_scan", "data_exfil", "brute_force"])
        if attack_type == "ddos":
            f = [np.random.uniform(800,2000), np.random.uniform(0.85,1.0),
                 np.random.uniform(0.1,0.3),  np.random.uniform(200,500),
                 np.random.uniform(100,300),  np.random.uniform(5,15)]
        elif attack_type == "port_scan":
            f = [np.random.normal(80,10), np.random.normal(0.2,0.05),
                 np.random.uniform(0.01,0.03), np.random.normal(45,5),
                 np.random.normal(15,3), np.random.uniform(200,500)]
        elif attack_type == "data_exfil":
            f = [np.random.normal(110,15), np.random.uniform(0.7,0.9),
                 np.random.normal(0.02,0.005), np.random.normal(5,2),
                 np.random.normal(10,2), np.random.normal(3,1)]
        else:
            f = [np.random.uniform(300,600), np.random.normal(0.4,0.05),
                 np.random.uniform(0.15,0.35), np.random.uniform(1,5),
                 np.random.normal(20,5), np.random.normal(2,0.5)]
    else:
        attack_type = None
        f = [np.random.normal(100,15), np.random.normal(0.35,0.08),
             np.random.normal(0.02,0.005), np.random.normal(50,10),
             np.random.normal(12,3), np.random.normal(20,5)]
    f = [max(0, x) for x in f]
    return f, is_attack, attack_type


def run_guardian_cycle() -> dict:
    _ensure_trained()
    f, is_attack, attack_type = _snapshot(anomaly_prob=0.08)
    features = np.array([f])
    score = float(_model.score_samples(features)[0])
    is_anomaly = score < -0.45
    return {
        "status": "THREAT_DETECTED" if is_anomaly else "NETWORK_NORMAL",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "anomaly_score": round(score, 4),
        "is_anomaly": is_anomaly,
        "threat_type": attack_type if is_anomaly else None,
        "network_features": {
            "packet_rate": round(f[0], 2),
            "bandwidth_util": round(f[1], 4),
            "error_rate": round(f[2], 4),
            "connection_count": round(f[3], 1),
            "latency_ms": round(f[4], 2),
            "port_diversity": round(f[5], 1),
        },
        "agent": "GUARDIAN",
        "summary": (
            f"Threat detected: {attack_type}. Score: {score:.4f}"
            if is_anomaly else f"Network normal. Score: {score:.4f}"
        ),
    }


if __name__ == "__main__":
    print("GUARDIAN — Test")
    _ensure_trained()
    threats = 0
    for i in range(10):
        r = run_guardian_cycle()
        threat = r["threat_type"] or "-"
        print(f"  Cycle {i+1:02d}: {r['status']:<20} score={r['anomaly_score']:+.4f}  threat={threat}")
        if r["is_anomaly"]:
            threats += 1
    print(f"Threats: {threats}/10")
