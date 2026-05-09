
"""
CORTEX - ORACLE Agent (Phase 2 Basic)
Failure probability prediction for Machine A, B, C.
Uses GradientBoostingClassifier (no extra deps needed).
Full Prophet + XGBoost in Phase 3.
"""
import numpy as np
import json
from datetime import datetime, timezone
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler

_models  = {}
_scalers = {}
_trained = False


def _generate_training_data(n=3000):
    np.random.seed(42)
    X, y6, y12, y24 = [], [], [], []
    for _ in range(n):
        tm  = np.random.normal(65, 8)
        ts  = np.random.uniform(0.5, 8)
        tmax= tm + ts * np.random.uniform(1, 4)
        vm  = np.random.normal(0.5, 0.2)
        vs  = np.random.uniform(0.01, 0.2)
        vmax= vm + vs * np.random.uniform(1, 4)
        ac  = np.random.poisson(1.5)
        ar  = ac / 6.0
        csm = np.random.uniform(0, 0.6)
        csx = csm + np.random.uniform(0, 0.4)
        cyc = np.random.uniform(0, 100)
        features = [tm, ts, tmax, vm, vs, vmax, ac, ar, csm, csx, cyc]
        stress = (
            0.25 * max(0, (tm - 70) / 20) +
            0.20 * max(0, (vm - 0.7) / 0.5) +
            0.20 * max(0, (ac - 2) / 8) +
            0.20 * csx +
            0.15 * max(0, (ts - 4) / 4)
        )
        stress = float(np.clip(stress + np.random.normal(0, 0.05), 0, 1))
        y6.append(1 if stress > 0.55 else 0)
        y12.append(1 if stress > 0.42 else 0)
        y24.append(1 if stress > 0.30 else 0)
        X.append(features)
    return np.array(X), np.array(y6), np.array(y12), np.array(y24)


def _ensure_trained():
    global _models, _scalers, _trained
    if _trained:
        return
    print("ORACLE: Training models...")
    X, y6, y12, y24 = _generate_training_data(3000)
    for machine in ["A", "B", "C"]:
        offset = {"A": 0.0, "B": 0.05, "C": 0.10}[machine]
        noise  = np.random.normal(offset, 0.02, X.shape[0])
        sc = StandardScaler()
        Xs = sc.fit_transform(X)
        mm = {}
        for horizon, y in [("6h", y6), ("12h", y12), ("24h", y24)]:
            y_adj = np.clip(y + (noise > 0.06).astype(int), 0, 1)
            clf = GradientBoostingClassifier(n_estimators=50, max_depth=3,
                                             learning_rate=0.1, random_state=42)
            clf.fit(Xs, y_adj)
            mm[horizon] = clf
        _models[machine]  = mm
        _scalers[machine] = sc
    _trained = True
    print("ORACLE: Ready.")


def predict_failure(machine_id: str, stats: dict) -> dict:
    _ensure_trained()
    m = machine_id if machine_id in ["A","B","C"] else "A"
    features = np.array([[
        stats.get("temp_mean", 65.0),
        stats.get("temp_std",  2.0),
        stats.get("temp_max",  70.0),
        stats.get("vib_mean",  0.5),
        stats.get("vib_std",   0.05),
        stats.get("vib_max",   0.65),
        stats.get("anomaly_count",       0),
        stats.get("anomaly_rate",        0.0),
        stats.get("combined_score_mean", 0.0),
        stats.get("combined_score_max",  0.0),
        stats.get("cycles_since_last",   50),
    ]])
    Xs = _scalers[m].transform(features)
    probs = {h: round(float(_models[m][h].predict_proba(Xs)[0][1]), 4)
             for h in ["6h","12h","24h"]}
    risk = "HIGH" if probs["6h"] > 0.7 else "MEDIUM" if probs["6h"] > 0.35 else "LOW"
    return {
        "machine_id": machine_id,
        "failure_probability_6h":  probs["6h"],
        "failure_probability_12h": probs["12h"],
        "failure_probability_24h": probs["24h"],
        "risk_level": risk,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def run_oracle_cycle(anomaly_history: list = None) -> dict:
    _ensure_trained()
    if anomaly_history is None:
        anomaly_history = []
    recent = anomaly_history[-36:]
    ac  = sum(1 for a in recent if a.get("is_anomaly", False))
    ar  = ac / max(len(recent), 1)
    scores = [a.get("combined_score", 0) for a in recent if a.get("is_anomaly")]
    csm = float(np.mean(scores)) if scores else 0.0
    csx = float(np.max(scores))  if scores else 0.0
    cycles_since = 0
    for i, a in enumerate(reversed(recent)):
        if not a.get("is_anomaly"):
            cycles_since = i
            break
    results = {}
    for machine in ["A", "B", "C"]:
        off = {"A":0,"B":1,"C":2}[machine]
        stats = {
            "temp_mean": 65.0 + off*2 + np.random.normal(0,1),
            "temp_std":  2.0 + off*0.5,
            "temp_max":  72.0 + off*3,
            "vib_mean":  0.5 + off*0.05,
            "vib_std":   0.05,
            "vib_max":   0.65 + off*0.05,
            "anomaly_count":       ac + off,
            "anomaly_rate":        ar + off*0.02,
            "combined_score_mean": csm,
            "combined_score_max":  csx,
            "cycles_since_last":   max(0, cycles_since - off*2),
        }
        results[f"machine_{machine}"] = predict_failure(machine, stats)
    return {
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "predictions": results,
        "trigger":    "scheduled",
        "agent":      "ORACLE",
    }


if __name__ == "__main__":
    print("ORACLE — Test")
    r = run_oracle_cycle()
    print(json.dumps(r, indent=2))
