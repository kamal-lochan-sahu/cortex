"""
CORTEX - ORACLE Agent (Phase 3 Full)
Type 1: GradientBoosting failure prediction (Phase 2 preserved)
Type 2: Prophet demand forecast (24h)
Type 3: Maintenance window optimizer
New: SHAP explainability for failure predictions
"""
import numpy as np
import json
import shap
from datetime import datetime, timezone, timedelta
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from agents.prophet_forecaster import predict_next_24h

# ─────────────────────────────────────────────
# GLOBALS
# ─────────────────────────────────────────────
_models   = {}
_scalers  = {}
_explainers = {}
_trained  = False

FEATURE_NAMES = [
    "temp_mean", "temp_std", "temp_max",
    "vib_mean",  "vib_std",  "vib_max",
    "anomaly_count", "anomaly_rate",
    "combined_score_mean", "combined_score_max",
    "cycles_since_last"
]

# ─────────────────────────────────────────────
# TRAINING DATA — same as Phase 2, unchanged
# ─────────────────────────────────────────────
def _generate_training_data(n=3000):
    np.random.seed(42)
    X, y6, y12, y24 = [], [], [], []
    for _ in range(n):
        tm   = np.random.normal(65, 8)
        ts   = np.random.uniform(0.5, 8)
        tmax = tm + ts * np.random.uniform(1, 4)
        vm   = np.random.normal(0.5, 0.2)
        vs   = np.random.uniform(0.01, 0.2)
        vmax = vm + vs * np.random.uniform(1, 4)
        ac   = np.random.poisson(1.5)
        ar   = ac / 6.0
        csm  = np.random.uniform(0, 0.6)
        csx  = csm + np.random.uniform(0, 0.4)
        cyc  = np.random.uniform(0, 100)
        features = [tm, ts, tmax, vm, vs, vmax, ac, ar, csm, csx, cyc]
        stress = (
            0.25 * max(0, (tm - 70) / 20) +
            0.20 * max(0, (vm - 0.7) / 0.5) +
            0.20 * max(0, (ac - 2) / 8) +
            0.20 * csx +
            0.15 * max(0, (ts - 4) / 4)
        )
        stress = float(np.clip(stress + np.random.normal(0, 0.05), 0, 1))
        y6.append(1  if stress > 0.55 else 0)
        y12.append(1 if stress > 0.42 else 0)
        y24.append(1 if stress > 0.30 else 0)
        X.append(features)
    return np.array(X), np.array(y6), np.array(y12), np.array(y24)


def _ensure_trained():
    global _models, _scalers, _explainers, _trained
    if _trained:
        return
    print("ORACLE: Training models + SHAP explainers...")
    X, y6, y12, y24 = _generate_training_data(3000)
    for machine in ["A", "B", "C"]:
        offset = {"A": 0.0, "B": 0.05, "C": 0.10}[machine]
        noise  = np.random.normal(offset, 0.02, X.shape[0])
        sc = StandardScaler()
        Xs = sc.fit_transform(X)
        mm = {}
        for horizon, y in [("6h", y6), ("12h", y12), ("24h", y24)]:
            y_adj = np.clip(y + (noise > 0.06).astype(int), 0, 1)
            clf = GradientBoostingClassifier(
                n_estimators=50, max_depth=3,
                learning_rate=0.1, random_state=42
            )
            clf.fit(Xs, y_adj)
            mm[horizon] = clf
        _models[machine]  = mm
        _scalers[machine] = sc
        # SHAP explainer — use 6h model as primary
        # TreeExplainer is fast + exact for tree models
        _explainers[machine] = shap.TreeExplainer(_models[machine]["6h"])
    _trained = True
    print("ORACLE: Ready — failure prediction + SHAP + Prophet active.")


# ─────────────────────────────────────────────
# TYPE 1 — FAILURE PREDICTION (Phase 2 preserved)
# ─────────────────────────────────────────────
def predict_failure(machine_id: str, stats: dict) -> dict:
    _ensure_trained()
    m = machine_id if machine_id in ["A", "B", "C"] else "A"
    features = np.array([[
        stats.get("temp_mean",           65.0),
        stats.get("temp_std",             2.0),
        stats.get("temp_max",            70.0),
        stats.get("vib_mean",             0.5),
        stats.get("vib_std",             0.05),
        stats.get("vib_max",             0.65),
        stats.get("anomaly_count",          0),
        stats.get("anomaly_rate",         0.0),
        stats.get("combined_score_mean",  0.0),
        stats.get("combined_score_max",   0.0),
        stats.get("cycles_since_last",     50),
    ]])
    Xs    = _scalers[m].transform(features)
    probs = {
        h: round(float(_models[m][h].predict_proba(Xs)[0][1]), 4)
        for h in ["6h", "12h", "24h"]
    }
    risk = (
        "HIGH"   if probs["6h"] > 0.7  else
        "MEDIUM" if probs["6h"] > 0.35 else
        "LOW"
    )
    return {
        "machine_id":              machine_id,
        "failure_probability_6h":  probs["6h"],
        "failure_probability_12h": probs["12h"],
        "failure_probability_24h": probs["24h"],
        "risk_level":              risk,
        "timestamp":               datetime.now(timezone.utc).isoformat(),
    }


# ─────────────────────────────────────────────
# TYPE 1 UPGRADE — SHAP EXPLAINABILITY
# "Why is Machine B at 89%?"
# Returns top 3 features driving the prediction
# ─────────────────────────────────────────────
def explain_failure(machine_id: str, stats: dict) -> dict:
    """
    Returns SHAP explanation for why a machine has high failure prob.
    Uses 6h horizon model as primary.

    Example output:
    {
      "machine_id": "B",
      "top_factors": [
        {"feature": "vib_trend", "shap_value": 0.34, "direction": "increases_risk"},
        {"feature": "temp_mean", "shap_value": 0.21, "direction": "increases_risk"},
        {"feature": "cycles_since_last", "shap_value": -0.08, "direction": "reduces_risk"}
      ],
      "summary": "Machine B failure risk driven by: vibration_trend (+0.34), temp_mean (+0.21)"
    }
    """
    _ensure_trained()
    m = machine_id if machine_id in ["A", "B", "C"] else "A"

    features = np.array([[
        stats.get("temp_mean",           65.0),
        stats.get("temp_std",             2.0),
        stats.get("temp_max",            70.0),
        stats.get("vib_mean",             0.5),
        stats.get("vib_std",             0.05),
        stats.get("vib_max",             0.65),
        stats.get("anomaly_count",          0),
        stats.get("anomaly_rate",         0.0),
        stats.get("combined_score_mean",  0.0),
        stats.get("combined_score_max",   0.0),
        stats.get("cycles_since_last",     50),
    ]])
    Xs         = _scalers[m].transform(features)
    shap_vals  = _explainers[machine_id].shap_values(Xs)

    # shap_vals shape: (1, 11) — one row, 11 features
    vals = shap_vals[0]

    # Sort by absolute impact — biggest drivers first
    indexed = sorted(
        enumerate(vals),
        key=lambda x: abs(x[1]),
        reverse=True
    )

    top_factors = []
    for idx, val in indexed[:3]:
        top_factors.append({
            "feature":   FEATURE_NAMES[idx],
            "shap_value": round(float(val), 4),
            "direction": "increases_risk" if val > 0 else "reduces_risk",
        })

    # Human-readable summary
    top2 = [
        f"{f['feature']} ({'+' if f['shap_value'] > 0 else ''}{f['shap_value']})"
        for f in top_factors[:2]
    ]
    summary = f"Machine {machine_id} failure risk driven by: {', '.join(top2)}"

    return {
        "machine_id":  machine_id,
        "top_factors": top_factors,
        "summary":     summary,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
    }


# ─────────────────────────────────────────────
# TYPE 2 — PROPHET DEMAND FORECAST
# Runs every 1 hour via APScheduler
# ─────────────────────────────────────────────
def get_demand_forecast() -> dict:
    """
    Returns next 24h production demand forecast from Prophet.
    Falls back to synthetic if model not trained yet.
    """
    predictions = predict_next_24h()
    return {
        "forecast":   predictions,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "horizon_hours": 24,
        "agent": "ORACLE",
    }


# ─────────────────────────────────────────────
# TYPE 3 — MAINTENANCE WINDOW OPTIMIZER
# Rule engine — not LLM
# Input: failure predictions + demand forecast
# Output: top 3 recommended maintenance windows
# ─────────────────────────────────────────────
def get_maintenance_windows(
    failure_results: dict = None,
    forecast: list = None
) -> dict:
    """
    Finds best maintenance windows by combining:
    - Failure probability per machine (when is it urgent?)
    - Production demand forecast (when is demand low?)

    Logic:
      score = failure_prob_6h * 0.6 + (1 - normalized_demand) * 0.4
      Higher score = better window to do maintenance

    Returns top 3 windows with machine, time, confidence, impact.
    """
    if forecast is None:
        forecast = predict_next_24h()

    if failure_results is None:
        failure_results = {}
        for machine in ["A", "B", "C"]:
            off = {"A": 0, "B": 1, "C": 2}[machine]
            failure_results[f"machine_{machine}"] = predict_failure(
                machine,
                {
                    "temp_mean": 65.0 + off * 2,
                    "temp_std":  2.0,
                    "temp_max":  72.0 + off * 3,
                    "vib_mean":  0.5 + off * 0.05,
                    "vib_std":   0.05,
                    "vib_max":   0.65 + off * 0.05,
                    "anomaly_count": off,
                    "anomaly_rate":  off * 0.02,
                    "combined_score_mean": 0.0,
                    "combined_score_max":  0.0,
                    "cycles_since_last":   50 - off * 5,
                }
            )

    # Normalize demand for scoring (0=lowest demand, 1=highest)
    demands  = [p["yhat"] for p in forecast]
    d_min, d_max = min(demands), max(demands)
    d_range  = d_max - d_min if d_max != d_min else 1.0

    windows = []
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    for machine in ["A", "B", "C"]:
        key      = f"machine_{machine}"
        fail_prob = failure_results.get(key, {}).get("failure_probability_6h", 0.3)
        risk      = failure_results.get(key, {}).get("risk_level", "LOW")

        # Find the 3 lowest-demand hours in next 24h
        sorted_hours = sorted(forecast, key=lambda p: p["yhat"])

        for slot in sorted_hours[:3]:
            hour_offset   = slot["hour"]
            window_start  = now + timedelta(hours=hour_offset)
            norm_demand   = (slot["yhat"] - d_min) / d_range

            # Composite score: failure urgency + low demand opportunity
            score = round(fail_prob * 0.6 + (1 - norm_demand) * 0.4, 4)

            # Impact classification
            if norm_demand < 0.25:
                impact = "safe"
                impact_label = "No production loss expected"
            elif norm_demand < 0.55:
                impact = "minor"
                impact_label = "Minor slowdown (~10%)"
            else:
                impact = "significant"
                impact_label = "Production loss likely"

            windows.append({
                "machine":        machine,
                "window_start":   window_start.isoformat(),
                "window_end":     (window_start + timedelta(hours=2)).isoformat(),
                "score":          score,
                "failure_prob":   round(fail_prob, 4),
                "demand_level":   round(norm_demand, 4),
                "impact":         impact,
                "impact_label":   impact_label,
                "risk_level":     risk,
                "confidence_pct": round(score * 100, 1),
            })

    # Sort by score descending, return top 3
    windows.sort(key=lambda w: w["score"], reverse=True)
    top3 = windows[:3]

    return {
        "windows":      top3,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agent":        "ORACLE",
    }


# ─────────────────────────────────────────────
# MAIN CYCLE — called by CORTEX_MASTER
# Runs all 3 prediction types sequentially
# ─────────────────────────────────────────────
def run_oracle_cycle(anomaly_history: list = None) -> dict:
    _ensure_trained()
    if anomaly_history is None:
        anomaly_history = []

    recent = anomaly_history[-36:]
    ac     = sum(1 for a in recent if a.get("is_anomaly", False))
    ar     = ac / max(len(recent), 1)
    scores = [a.get("combined_score", 0) for a in recent if a.get("is_anomaly")]
    csm    = float(np.mean(scores)) if scores else 0.0
    csx    = float(np.max(scores))  if scores else 0.0

    cycles_since = 0
    for i, a in enumerate(reversed(recent)):
        if not a.get("is_anomaly"):
            cycles_since = i
            break

    # Type 1 — failure predictions for all machines
    failure_results = {}
    for machine in ["A", "B", "C"]:
        off = {"A": 0, "B": 1, "C": 2}[machine]
        stats = {
            "temp_mean":           65.0 + off * 2 + np.random.normal(0, 1),
            "temp_std":            2.0 + off * 0.5,
            "temp_max":            72.0 + off * 3,
            "vib_mean":            0.5 + off * 0.05,
            "vib_std":             0.05,
            "vib_max":             0.65 + off * 0.05,
            "anomaly_count":       ac + off,
            "anomaly_rate":        ar + off * 0.02,
            "combined_score_mean": csm,
            "combined_score_max":  csx,
            "cycles_since_last":   max(0, cycles_since - off * 2),
        }
        failure_results[f"machine_{machine}"] = predict_failure(machine, stats)

    # Type 2 — demand forecast
    forecast_data = get_demand_forecast()

    # Type 3 — maintenance windows
    maintenance   = get_maintenance_windows(
        failure_results=failure_results,
        forecast=forecast_data["forecast"]
    )

    return {
        "timestamp":    datetime.now(timezone.utc).isoformat(),
        "predictions":  failure_results,
        "forecast":     forecast_data,
        "maintenance":  maintenance,
        "trigger":      "scheduled",
        "agent":        "ORACLE",
    }


# ─────────────────────────────────────────────
# SELF TEST
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 55)
    print("ORACLE Phase 3 — Full Self Test")
    print("=" * 55)

    print("\n[1] Failure Prediction + SHAP")
    result = run_oracle_cycle()
    for k, v in result["predictions"].items():
        print(f"  {k}: 6h={v['failure_probability_6h']} risk={v['risk_level']}")

    print("\n[2] SHAP Explanation — Machine B")
    exp = explain_failure("B", {
        "temp_mean": 72.0, "temp_std": 3.5, "temp_max": 81.0,
        "vib_mean": 0.68,  "vib_std": 0.12, "vib_max": 0.95,
        "anomaly_count": 5, "anomaly_rate": 0.14,
        "combined_score_mean": 0.45, "combined_score_max": 0.82,
        "cycles_since_last": 120,
    })
    print(f"  Summary: {exp['summary']}")
    for f in exp["top_factors"]:
        print(f"    {f['feature']}: {f['shap_value']} ({f['direction']})")

    print("\n[3] Demand Forecast — first 5 hours")
    fc = result["forecast"]["forecast"][:5]
    for p in fc:
        print(f"  Hour {p['hour']}: yhat={p['yhat']} [{p['yhat_lower']} - {p['yhat_upper']}]")

    print("\n[4] Maintenance Windows — top 3")
    for w in result["maintenance"]["windows"]:
        print(f"  Machine {w['machine']} | {w['window_start']} | score={w['score']} | {w['impact']}")

    print("\nAll 3 ORACLE types working.")
