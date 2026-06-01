# backend/agents/prophet_forecaster.py

import os
import pickle
import logging
from datetime import datetime, timedelta
from typing import Optional
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# MODEL PATH — relative to this file's location
# ~/projects/cortex/backend/agents/../models/
# → ~/projects/cortex/backend/models/oracle_prophet/
# ─────────────────────────────────────────────
MODEL_DIR = os.path.join(
    os.path.dirname(__file__),
    "..", "models", "oracle_prophet"
)
MODEL_PATH = os.path.join(MODEL_DIR, "prophet_model.pkl")

# ─────────────────────────────────────────────
# MODULE-LEVEL LOAD — happens once at import
# If model missing → _model stays None → fallback
# ─────────────────────────────────────────────
_model = None

def _load_model():
    global _model
    if not os.path.exists(MODEL_PATH):
        logger.warning(
            f"Prophet model not found at {MODEL_PATH}. "
            "Running in FALLBACK mode — synthetic predictions active."
        )
        return
    try:
        with open(MODEL_PATH, "rb") as f:
            _model = pickle.load(f)
        logger.info("Prophet model loaded successfully.")
    except Exception as e:
        logger.error(f"Prophet model load failed: {e}")

# This runs when the module is first imported
_load_model()


# ─────────────────────────────────────────────
# CORE FUNCTION — called by ORACLE agent
# Returns next 24 hours, one dict per hour
# ─────────────────────────────────────────────
def predict_next_24h(
    reference_time: Optional[datetime] = None
) -> list[dict]:
    """
    Returns 24 hourly predictions starting from reference_time.

    Each dict contains:
        ds          : ISO timestamp string
        yhat        : predicted production rate (units/hr)
        yhat_lower  : lower confidence bound
        yhat_upper  : upper confidence bound
        hour        : 0-23 (for frontend x-axis)
    """
    if reference_time is None:
        reference_time = datetime.utcnow()

    # Round down to current hour for clean alignment
    reference_time = reference_time.replace(
        minute=0, second=0, microsecond=0
    )

    if _model is not None:
        return _predict_with_prophet(reference_time)
    else:
        return _predict_fallback(reference_time)


# ─────────────────────────────────────────────
# PROPHET INFERENCE PATH
# ─────────────────────────────────────────────
def _predict_with_prophet(start: datetime) -> list[dict]:
    # Prophet needs a DataFrame with column 'ds'
    future_timestamps = [
        start + timedelta(hours=i) for i in range(24)
    ]
    future_df = pd.DataFrame({"ds": future_timestamps})

    forecast = _model.predict(future_df)

    results = []
    for i, row in forecast.iterrows():
        results.append({
            "ds": row["ds"].isoformat(),
            "yhat": round(float(row["yhat"]), 2),
            "yhat_lower": round(float(row["yhat_lower"]), 2),
            "yhat_upper": round(float(row["yhat_upper"]), 2),
            "hour": i,
        })
    return results


# ─────────────────────────────────────────────
# FALLBACK PATH — synthetic but realistic
# Simulates industrial production pattern:
#   - Low production: 00:00–06:00 (night shift low)
#   - Ramp up: 06:00–08:00
#   - Peak: 08:00–17:00 (day shift)
#   - Taper: 17:00–20:00
#   - Moderate: 20:00–00:00 (evening shift)
# ─────────────────────────────────────────────
def _predict_fallback(start: datetime) -> list[dict]:
    # Baseline production profile per hour (0-23)
    # Units: production rate (arbitrary industrial units/hr)
    HOURLY_PROFILE = [
        35, 30, 28, 27, 28, 32,   # 00-05: night low
        45, 62, 78, 85, 88, 90,   # 06-11: morning ramp + peak
        88, 87, 90, 91, 89, 82,   # 12-17: peak sustained
        70, 60, 55, 52, 48, 40,   # 18-23: evening taper
    ]
    UNCERTAINTY_BAND = 8.0  # ± band width

    results = []
    for i in range(24):
        ts = start + timedelta(hours=i)
        hour_of_day = ts.hour

        base = HOURLY_PROFILE[hour_of_day]
        # Small noise so it doesn't look perfectly flat
        noise = np.random.uniform(-2.0, 2.0)
        yhat = round(base + noise, 2)

        results.append({
            "ds": ts.isoformat(),
            "yhat": yhat,
            "yhat_lower": round(yhat - UNCERTAINTY_BAND, 2),
            "yhat_upper": round(yhat + UNCERTAINTY_BAND, 2),
            "hour": i,
        })
    return results


# ─────────────────────────────────────────────
# QUICK SELF-TEST — run this file directly
# python3 prophet_forecaster.py
# ─────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("\n=== Prophet Forecaster Self-Test ===")
    predictions = predict_next_24h()
    print(f"Mode: {'PROPHET' if _model else 'FALLBACK'}")
    print(f"Generated {len(predictions)} hourly predictions\n")
    print(f"{'Hour':<6} {'Time':<22} {'yhat':>8} {'lower':>8} {'upper':>8}")
    print("-" * 56)
    for p in predictions:
        print(
            f"{p['hour']:<6} {p['ds']:<22} "
            f"{p['yhat']:>8} {p['yhat_lower']:>8} {p['yhat_upper']:>8}"
        )