"""
CORTEX Phase 4 — HERMES Supply Chain Agent
hermes.py

4 Intelligence Layers:
  Layer 1: Inventory Monitor      — every 30 min
  Layer 2: Supplier Risk Monitor  — every 6 hours
  Layer 3: ORACLE Demand Coupling — every 1 hour
  Layer 4: Stockout Risk Update   — every 30 min

RAM cost: ~20MB (pure logic, no ML model)
Run: python3 -m hermes.hermes
"""

import os
import sys
import time
import random
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timezone
from dotenv import load_dotenv

from hermes.hermes_tools import (
    inventory_checker_tool,
    supplier_risk_scorer_tool,
    reorder_trigger_tool,
    demand_forecast_reader_tool,
    stockout_risk_calculator_tool,
)

# ── Logging Setup ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [HERMES] %(levelname)s — %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("hermes")

# ── DB Setup ───────────────────────────────────────────────
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(dotenv_path=env_path)
DATABASE_URL = os.getenv("DATABASE_URL")

# ── Cycle Counters ─────────────────────────────────────────
# Har cycle 30 min = 1 unit
# Layer 2 (supplier): har 12 cycles = 6 hours
# Layer 3 (ORACLE):   har  2 cycles = 1 hour
SUPPLIER_CHECK_EVERY = 12
ORACLE_CHECK_EVERY   = 2


def get_conn():
    return psycopg2.connect(DATABASE_URL)


# ══════════════════════════════════════════════════════════
# LAYER 1 — Inventory Monitor
# Saare components check karo
# Agar stock <= reorder_point → auto-reorder
# ══════════════════════════════════════════════════════════
def layer1_inventory_monitor() -> dict:
    """
    Returns summary dict:
    {
      'checked': 10,
      'orders_triggered': [...],
      'critical_count': 1,
      'high_count': 2
    }
    """
    log.info("Layer 1: Inventory Monitor starting...")

    # Step 1: Risk levels fresh recalculate karo
    updated = stockout_risk_calculator_tool()

    orders_triggered = []
    critical_count   = 0
    high_count       = 0

    for component in updated:
        cid   = component['component_id']
        stock = component['current_stock']
        rop   = component['reorder_point']
        risk  = component['risk_level']
        days  = component['days_of_stock']

        if risk == "CRITICAL":
            critical_count += 1
        elif risk == "HIGH":
            high_count += 1

        # Reorder trigger condition
        # stock <= reorder_point → order banana hai
        if stock <= rop:
            log.warning(
                f"  ⚠️  {cid}: stock={stock} <= ROP={rop} "
                f"[{risk}] days={days} → triggering reorder"
            )

            # CRITICAL: immediate order
            reason = "STOCKOUT_CRITICAL" if risk == "CRITICAL" \
                     else "REORDER_POINT_BREACH"

            order = reorder_trigger_tool(
                component_id   = cid,
                trigger_reason = reason,
                trigger_source = "HERMES_AUTO"
            )

            if order.get("skipped"):
                # Pending order already exists — skip silently
                log.info(
                    f"  ⏭️  {cid}: order skipped "
                    f"(pending order already exists)"
                )
            elif "error" not in order:
                log.info(
                    f"  ✅ Order placed: {order['order_id']} | "
                    f"supplier={order['supplier_id']} | "
                    f"qty={order['quantity_ordered']} | "
                    f"cost=€{order['total_cost_eur']:.2f}"
                )
                if order.get('supplier_switched'):
                    log.warning(
                        f"  🔄 Supplier switched: "
                        f"{order['previous_supplier']} → {order['supplier_id']}"
                    )
                orders_triggered.append(order)
            else:
                log.error(f"  ❌ Order failed: {order['error']}")
        else:
            log.info(
                f"  ✅ {cid:<30} stock={stock:>3} "
                f"ROP={rop} days={days} [{risk}]"
            )

    summary = {
        "checked":          len(updated),
        "orders_triggered": orders_triggered,
        "critical_count":   critical_count,
        "high_count":       high_count,
    }

    log.info(
        f"Layer 1 complete: {len(updated)} checked | "
        f"{len(orders_triggered)} orders | "
        f"CRITICAL={critical_count} HIGH={high_count}"
    )
    return summary


# ══════════════════════════════════════════════════════════
# LAYER 2 — Supplier Risk Monitor
# Har 6 hours scores recalculate karo
# 10% chance delay simulate karo (Phase 4 mock)
# ══════════════════════════════════════════════════════════
def layer2_supplier_monitor() -> dict:
    """
    Returns supplier health summary
    """
    log.info("Layer 2: Supplier Risk Monitor starting...")

    # 10% chance: koi ek supplier delay karega
    simulate = random.random() < 0.10
    delay_supplier = None

    if simulate:
        # Random supplier choose karo delay ke liye
        suppliers_pool = ["SUP_A", "SUP_B", "SUP_C", "SUP_D"]
        delay_supplier = random.choice(suppliers_pool)
        log.warning(f"  ⚡ Delay event simulated for {delay_supplier}")

    updated = supplier_risk_scorer_tool(
        simulate_delay    = simulate,
        delay_supplier_id = delay_supplier
    )

    at_risk = []
    for s in updated:
        status = s['status']
        score  = s['reliability_score']
        otd    = s['otd_rate']
        log.info(
            f"  {'⚠️' if status == 'AT_RISK' else '✅'} "
            f"{s['supplier_id']} — {s['supplier_name']:<25} "
            f"score={score:.1f} OTD={otd:.1f}% [{status}]"
        )
        if status == "AT_RISK":
            at_risk.append(s['supplier_id'])

    if at_risk:
        log.warning(
            f"Layer 2: AT_RISK suppliers: {at_risk} "
            f"— will be avoided on next reorder"
        )
    else:
        log.info("Layer 2 complete: All suppliers healthy ✅")

    return {
        "suppliers_checked": len(updated),
        "at_risk":           at_risk,
        "delay_simulated":   delay_supplier
    }


# ══════════════════════════════════════════════════════════
# LAYER 3 — ORACLE Demand Coupling
# ORACLE ka latest forecast padho
# Agar failure_prob >= 80% → pre-position inventory
#
# Machine → Component mapping:
# Machine_A → precision_bearings_v2, encoder_discs_100ppr
# Machine_B → servo_motors_type_a, control_pcb_unit
# Machine_C → hydraulic_seals_set, pneumatic_cylinders
# Any       → power_supply_24v, cooling_fans_48v (shared)
# ══════════════════════════════════════════════════════════

MACHINE_COMPONENTS = {
    "Machine_A": ["precision_bearings_v2", "encoder_discs_100ppr"],
    "Machine_B": ["servo_motors_type_a",   "control_pcb_unit"],
    "Machine_C": ["hydraulic_seals_set",   "pneumatic_cylinders"],
}
SHARED_COMPONENTS = ["power_supply_24v", "cooling_fans_48v"]


def layer3_oracle_coupling() -> dict:
    """
    ORACLE forecast padhta hai.
    High failure probability → pre-positioning order.
    Returns action summary.
    """
    log.info("Layer 3: ORACLE Demand Coupling starting...")

    signal = demand_forecast_reader_tool()

    if not signal.get("has_signal"):
        reason = signal.get("reason", "No signal")
        log.info(f"  Layer 3: No ORACLE signal — {reason}")
        return {"action": "none", "reason": reason}

    machine  = signal["bottleneck_machine"]
    prob     = signal["failure_probability"]
    horizon  = signal["forecast_horizon_hours"]

    log.warning(
        f"  🔴 ORACLE signal: {machine} failure={prob:.0%} "
        f"within {horizon}h → pre-positioning inventory"
    )

    # Components determine karo
    components_to_preposition = MACHINE_COMPONENTS.get(machine, [])
    components_to_preposition += SHARED_COMPONENTS

    # Duplicates remove karo
    components_to_preposition = list(set(components_to_preposition))

    preposition_orders = []
    for cid in components_to_preposition:
        # Current stock check karo
        items = inventory_checker_tool(component_id=cid)
        if not items:
            continue
        item = items[0]

        # Pre-position sirf tabhi karo jab stock LOW ya MEDIUM ho
        # CRITICAL/HIGH mein already normal reorder hoga
        if item['risk_level'] in ("LOW", "MEDIUM"):
            log.info(
                f"  📦 Pre-positioning {cid} "
                f"(current={item['current_stock']}, "
                f"risk={item['risk_level']})"
            )
            order = reorder_trigger_tool(
                component_id   = cid,
                trigger_reason = "ORACLE_PREPOSITION",
                trigger_source = "HERMES_ORACLE_COUPLING"
            )
            if "error" not in order:
                log.info(
                    f"  ✅ Pre-position order: {order['order_id']} | "
                    f"qty={order['quantity_ordered']} (+20%)"
                )
                preposition_orders.append(order)

    log.info(
        f"Layer 3 complete: {len(preposition_orders)} "
        f"pre-position orders triggered"
    )
    return {
        "action":               "preposition",
        "machine":              machine,
        "failure_probability":  prob,
        "orders":               preposition_orders
    }


# ══════════════════════════════════════════════════════════
# LAYER 4 — SCRIBE Summary Save
# Har cycle ka summary PostgreSQL mein save karo
# SCRIBE isse padhega Factory Health Score ke liye
# ══════════════════════════════════════════════════════════
def layer4_save_summary(cycle_summary: dict):
    """
    HERMES cycle summary scribe_reports mein save karta hai.
    Schema: timestamp, report_type, content, sentinel_log_id
    """
    conn = get_conn()
    try:
        cur = conn.cursor()

        critical          = cycle_summary.get("critical_count", 0)
        high              = cycle_summary.get("high_count", 0)
        at_risk_suppliers = len(
            cycle_summary.get("supplier_summary", {}).get("at_risk", [])
        )
        sc_health = max(
            0,
            100 - (critical * 15) - (high * 8) - (at_risk_suppliers * 5)
        )

        content = (
            f"HERMES cycle complete | "
            f"Components checked: {cycle_summary.get('checked', 0)} | "
            f"Orders triggered: {cycle_summary.get('orders_count', 0)} | "
            f"CRITICAL: {critical} | HIGH: {high} | "
            f"SC Health: {sc_health}/100"
        )

        cur.execute("""
            INSERT INTO scribe_reports
                (timestamp, report_type, content)
            VALUES
                (NOW(), 'HERMES_CYCLE', %s)
        """, (content,))

        conn.commit()
        log.info(f"Layer 4: Summary saved — SC Health={sc_health}/100")
    except Exception as e:
        log.warning(f"Layer 4: Could not save to scribe_reports: {e}")
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════
# MAIN CYCLE — Sab layers ko orchestrate karta hai
# ══════════════════════════════════════════════════════════
def run_hermes_cycle(cycle_number: int = 1) -> dict:
    """
    Ek complete HERMES cycle run karta hai.
    APScheduler isse har 30 min call karega.
    Manual test ke liye seedha bhi call kar sakte ho.
    """
    log.info("=" * 55)
    log.info(f"HERMES CYCLE #{cycle_number} — {datetime.now(timezone.utc).strftime('%H:%M UTC')}")
    log.info("=" * 55)

    cycle_summary = {}

    # ── Layer 1: Always run (every 30 min) ────────────────
    inv_summary = layer1_inventory_monitor()
    cycle_summary.update({
        "checked":        inv_summary["checked"],
        "orders_count":   len(inv_summary["orders_triggered"]),
        "critical_count": inv_summary["critical_count"],
        "high_count":     inv_summary["high_count"],
    })

    # ── Layer 2: Every 6 hours ─────────────────────────────
    if cycle_number % SUPPLIER_CHECK_EVERY == 0 or cycle_number == 1:
        sup_summary = layer2_supplier_monitor()
        cycle_summary["supplier_summary"] = sup_summary
    else:
        log.info(
            f"Layer 2: Skipping — next check in "
            f"{SUPPLIER_CHECK_EVERY - (cycle_number % SUPPLIER_CHECK_EVERY)} cycles"
        )
        cycle_summary["supplier_summary"] = {"at_risk": []}

    # ── Layer 3: Every 1 hour ──────────────────────────────
    if cycle_number % ORACLE_CHECK_EVERY == 0 or cycle_number == 1:
        oracle_summary = layer3_oracle_coupling()
        cycle_summary["oracle_summary"] = oracle_summary
    else:
        log.info("Layer 3: Skipping — next check in 1 cycle")
        cycle_summary["oracle_summary"] = {"action": "skipped"}

    # ── Layer 4: Always save summary ──────────────────────
    layer4_save_summary(cycle_summary)

    log.info("=" * 55)
    log.info(f"HERMES CYCLE #{cycle_number} COMPLETE ✅")
    log.info("=" * 55)

    return cycle_summary


# ══════════════════════════════════════════════════════════
# STANDALONE RUN — Direct test ke liye
# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    log.info("HERMES agent starting in standalone mode...")
    log.info("Press Ctrl+C to stop\n")

    cycle = 1
    while True:
        try:
            result = run_hermes_cycle(cycle_number=cycle)
            cycle += 1
            log.info(f"\nNext cycle in 30 seconds (demo mode)...")
            log.info("(In production: APScheduler runs every 30 min)\n")
            time.sleep(30)
        except KeyboardInterrupt:
            log.info("\nHERMES stopped by user.")
            sys.exit(0)
        except Exception as e:
            log.error(f"Cycle error: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(10)
