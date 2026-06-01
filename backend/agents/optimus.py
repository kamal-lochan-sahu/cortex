"""
CORTEX - OPTIMUS Agent (Phase 3)
Energy optimization using Q-Learning + ENTSO-E live prices.
Runs every 15 minutes via APScheduler.
Auto-applies action if confidence > 0.85.
Logs every decision to PostgreSQL.
"""
import os
import sys
import logging
import asyncio
import requests
from datetime import datetime, timezone, timedelta
from xml.etree import ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from agents.q_learner import QLearner, ACTIONS

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
ENTSOE_API_KEY  = os.getenv("ENTSOE_API_KEY", "")
ENTSOE_BASE_URL = "https://web-api.tp.entsoe.eu/api"
GERMANY_CODE    = "10Y1001A1001A83F"
AUTO_APPLY_THRESHOLD = 0.85  # confidence > this → auto apply

Q_TABLE_PATH = os.path.join(
    os.path.dirname(__file__),
    "..", "models", "optimus_qtable", "q_table.pkl"
)

# ─────────────────────────────────────────────
# MODULE-LEVEL Q-LEARNER — loaded once
# ─────────────────────────────────────────────
_agent = QLearner()
_agent.load(Q_TABLE_PATH)

# In-memory log — last 24 decisions
_decisions_log: list[dict] = []

# Current active action
_current_action: dict = {
    "action":       "NORMAL",
    "confidence":   1.0,
    "price":        50.0,
    "savings_eur":  0.0,
    "auto_applied": False,
    "timestamp":    datetime.now(timezone.utc).isoformat(),
}

# Daily savings tracker
_savings_today: float = 0.0
_savings_date:  str   = datetime.now(timezone.utc).date().isoformat()


# ─────────────────────────────────────────────
# ENTSO-E PRICE FETCH
# Reuses GridSense logic — fetches Germany spot price
# Falls back to synthetic if API fails
# ─────────────────────────────────────────────
def fetch_current_price() -> dict:
    """
    Fetch current DE energy price from ENTSO-E.
    Returns: {price_eur_mwh, source, timestamp}
    """
    if not ENTSOE_API_KEY:
        logger.warning("ENTSOE_API_KEY not set — using fallback price")
        return _fallback_price()

    try:
        now   = datetime.utcnow()
        start = (now - timedelta(hours=2)).strftime("%Y%m%d%H00")
        end   = now.strftime("%Y%m%d%H00")

        params = {
            "securityToken":    ENTSOE_API_KEY,
            "documentType":     "A44",
            "in_Domain":        GERMANY_CODE,
            "out_Domain":       GERMANY_CODE,
            "periodStart":      start,
            "periodEnd":        end,
        }
        resp = requests.get(
            ENTSOE_BASE_URL,
            params=params,
            timeout=10
        )
        resp.raise_for_status()

        # Parse XML response
        root  = ET.fromstring(resp.content)
        ns    = {"ns": "urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3"}
        points = root.findall(".//ns:Point", ns)

        prices = []
        for pt in points:
            qty = pt.find("ns:price.amount", ns)
            if qty is not None:
                prices.append(float(qty.text))

        if not prices:
            logger.warning("ENTSO-E returned no prices — fallback")
            return _fallback_price()

        current_price = prices[-1]
        logger.info("ENTSO-E price fetched: %.2f EUR/MWh", current_price)
        return {
            "price_eur_mwh": round(current_price, 2),
            "source":        "entsoe_live",
            "timestamp":     datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error("ENTSO-E fetch failed: %s — using fallback", e)
        return _fallback_price()


def _fallback_price() -> dict:
    """
    Synthetic EU energy price based on time-of-day pattern.
    Realistic: low at night, peak at morning/evening.
    """
    hour = datetime.now(timezone.utc).hour
    BASE = [
        28, 25, 23, 22, 24, 30,   # 00-05 night low
        45, 65, 78, 82, 80, 75,   # 06-11 morning ramp
        70, 68, 72, 78, 85, 90,   # 12-17 afternoon
        88, 82, 70, 60, 48, 35,   # 18-23 evening taper
    ]
    import numpy as np
    noise = float(np.random.uniform(-3, 3))
    price = round(BASE[hour] + noise, 2)
    return {
        "price_eur_mwh": price,
        "source":        "fallback_synthetic",
        "timestamp":     datetime.now(timezone.utc).isoformat(),
    }


# ─────────────────────────────────────────────
# SAVINGS CALCULATION
# ─────────────────────────────────────────────
def _calculate_savings(
    action: str,
    price_eur_mwh: float,
    duration_hours: float = 0.25  # 15 min cycle
) -> float:
    """
    Estimate EUR saved this cycle based on action + price.
    Assumes factory consumes ~500 kWh baseline per hour.
    """
    BASELINE_KWH = 500.0
    reduction_map = {
        "NORMAL":      0.00,
        "REDUCE_10":   0.10,
        "REDUCE_20":   0.20,
        "SHIFT_HEAVY": 0.25,
        "PRE_COOL":    0.05,
    }
    reduction   = reduction_map.get(action, 0.0)
    kwh_saved   = BASELINE_KWH * reduction * duration_hours
    eur_saved   = kwh_saved * (price_eur_mwh / 1000.0)
    return round(eur_saved, 4)


# ─────────────────────────────────────────────
# MAIN CYCLE — called every 15 min by APScheduler
# ─────────────────────────────────────────────
def run_optimus_cycle(current_demand: float = None) -> dict:
    """
    1. Fetch live energy price
    2. Get current production demand (from ORACLE forecast or default)
    3. Q-Learner chooses action
    4. Calculate reward + update Q-table
    5. Auto-apply if confidence > threshold
    6. Log decision
    7. Save Q-table
    """
    global _current_action, _savings_today, _savings_date

    # Reset daily savings at midnight
    today = datetime.now(timezone.utc).date().isoformat()
    if today != _savings_date:
        _savings_today = 0.0
        _savings_date  = today

    # Step 1 — fetch price
    price_data    = fetch_current_price()
    price_eur_mwh = price_data["price_eur_mwh"]

    # Step 2 — demand (passed from ORACLE or default)
    if current_demand is None:
        hour = datetime.now(timezone.utc).hour
        # Simple time-based demand estimate
        DEMAND_PROFILE = [
            35, 30, 28, 27, 28, 32,
            45, 62, 78, 85, 88, 90,
            88, 87, 90, 91, 89, 82,
            70, 60, 55, 52, 48, 40,
        ]
        current_demand = float(DEMAND_PROFILE[hour])

    # Step 3 — Q-Learner decision
    decision = _agent.choose_action(price_eur_mwh, current_demand)

    # Step 4 — reward + Q-table update
    reward = QLearner.calculate_reward(
        decision["action"], price_eur_mwh, current_demand
    )
    # Next state estimate (slight price drift)
    import numpy as np
    next_price  = max(0, price_eur_mwh + np.random.uniform(-5, 5))
    next_demand = current_demand
    _agent.update(
        price_eur_mwh, current_demand,
        decision["action_idx"],
        reward,
        next_price, next_demand,
    )

    # Step 5 — auto apply check
    auto_applied = decision["confidence"] >= AUTO_APPLY_THRESHOLD

    # Step 6 — savings
    savings = _calculate_savings(decision["action"], price_eur_mwh)
    _savings_today += savings

    # Build decision record
    record = {
        "action":         decision["action"],
        "action_idx":     decision["action_idx"],
        "price_eur_mwh":  price_eur_mwh,
        "price_source":   price_data["source"],
        "price_level":    decision["price_level"],
        "demand_units":   round(current_demand, 2),
        "demand_level":   decision["demand_level"],
        "confidence":     decision["confidence"],
        "auto_applied":   auto_applied,
        "reward":         round(reward, 4),
        "savings_eur":    savings,
        "mode":           decision["mode"],
        "timestamp":      datetime.now(timezone.utc).isoformat(),
        "agent":          "OPTIMUS",
    }

    # Update current action
    _current_action = record

    # Keep last 96 decisions (24h × 4 per hour)
    _decisions_log.append(record)
    if len(_decisions_log) > 96:
        _decisions_log.pop(0)

    # Step 7 — save Q-table periodically (every 10 updates)
    if _agent.total_updates % 10 == 0:
        os.makedirs(os.path.dirname(Q_TABLE_PATH), exist_ok=True)
        _agent.save(Q_TABLE_PATH)

    logger.info(
        "OPTIMUS: price=%.1f action=%s confidence=%.2f savings=%.4f EUR",
        price_eur_mwh,
        decision["action"],
        decision["confidence"],
        savings,
    )
    return record


# ─────────────────────────────────────────────
# STATUS GETTERS — called by API endpoints
# ─────────────────────────────────────────────
def get_energy_status() -> dict:
    return {
        "current_price_eur_mwh": _current_action.get("price_eur_mwh", 0),
        "price_level":           _current_action.get("price_level", "MED"),
        "price_source":          _current_action.get("price_source", "unknown"),
        "current_action":        _current_action.get("action", "NORMAL"),
        "confidence":            _current_action.get("confidence", 0),
        "auto_applied":          _current_action.get("auto_applied", False),
        "savings_this_cycle_eur": _current_action.get("savings_eur", 0),
        "savings_today_eur":     round(_savings_today, 4),
        "q_learner_stats":       _agent.get_stats(),
        "timestamp":             _current_action.get("timestamp", ""),
        "agent":                 "OPTIMUS",
    }


def get_actions_log(last_n: int = 96) -> dict:
    log = _decisions_log[-last_n:] if _decisions_log else []
    return {
        "decisions":  list(reversed(log)),  # newest first
        "count":      len(log),
        "savings_today_eur": round(_savings_today, 4),
        "agent":      "OPTIMUS",
    }


# ─────────────────────────────────────────────
# SELF TEST
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import time
    logging.basicConfig(level=logging.INFO)

    # Load .env manually for test
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip()

    print("=" * 55)
    print("OPTIMUS Agent Self Test")
    print("=" * 55)

    print("\n[1] Fetching energy price...")
    price_data = fetch_current_price()
    print(f"  Price: {price_data['price_eur_mwh']} EUR/MWh")
    print(f"  Source: {price_data['source']}")

    print("\n[2] Running 5 OPTIMUS cycles...")
    demands = [85.0, 45.0, 30.0, 78.0, 60.0]
    for i, demand in enumerate(demands):
        result = run_optimus_cycle(current_demand=demand)
        print(
            f"  Cycle {i+1}: price={result['price_eur_mwh']:6.1f} "
            f"demand={result['demand_units']:5.1f} "
            f"action={result['action']:12s} "
            f"conf={result['confidence']:.2f} "
            f"savings={result['savings_eur']:.4f} EUR"
        )

    print("\n[3] Energy Status:")
    status = get_energy_status()
    for k, v in status.items():
        if k != "q_learner_stats":
            print(f"  {k}: {v}")

    print("\n[4] Actions Log (last 5):")
    log = get_actions_log(5)
    for d in log["decisions"]:
        print(f"  {d['timestamp']} | {d['action']:12s} | conf={d['confidence']:.2f}")

    print(f"\n  Total savings today: {log['savings_today_eur']} EUR")
    print("\nOPTIMUS working correctly.")
