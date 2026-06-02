"""
CORTEX Phase 4 — HERMES Supply Chain Agent
hermes_tools.py

5 tools — pure DB operations, zero business logic:
  1. inventory_checker_tool      — stock levels padhna
  2. supplier_risk_scorer_tool   — scores recalculate karna
  3. reorder_trigger_tool        — order place karna
  4. demand_forecast_reader_tool — ORACLE se forecast padhna
  5. stockout_risk_calculator_tool — risk level update karna
"""

import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# ── DB Setup ───────────────────────────────────────────────
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(dotenv_path=env_path)
DATABASE_URL = os.getenv("DATABASE_URL")


def get_conn():
    """Fresh connection har tool call pe — RAM efficient"""
    return psycopg2.connect(DATABASE_URL)


# ══════════════════════════════════════════════════════════
# TOOL 1 — Inventory Checker
# Kya karta hai: saare components ka current stock padhta hai
# Return: list of dicts with full inventory data
# ══════════════════════════════════════════════════════════
def inventory_checker_tool(component_id: Optional[str] = None) -> list:
    """
    Ek ya saare components ka stock data return karta hai.
    component_id=None → saare 10 components
    component_id='precision_bearings_v2' → sirf woh ek
    """
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        if component_id:
            cur.execute("""
                SELECT * FROM hermes_inventory
                WHERE component_id = %s
            """, (component_id,))
        else:
            cur.execute("""
                SELECT * FROM hermes_inventory
                ORDER BY risk_level DESC, current_stock ASC
            """)
            # ORDER BY: CRITICAL pehle, phir HIGH, MEDIUM, LOW
            # Iss se HERMES ko sabse urgent items pehle milte hain
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════
# TOOL 2 — Supplier Risk Scorer
# Kya karta hai: reliability scores recalculate karta hai
# Formula: (otd*0.6) + (quality*0.3) + (price_factor*0.1)
# Side effect: DB update karta hai scores aur status
# ══════════════════════════════════════════════════════════
def supplier_risk_scorer_tool(
    simulate_delay: bool = False,
    delay_supplier_id: Optional[str] = None
) -> list:
    """
    Saare suppliers ke scores recalculate karta hai.
    simulate_delay=True → ek supplier ko delay simulate karta hai
    Returns: updated supplier list with new scores + status
    """
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM hermes_suppliers")
        suppliers = [dict(row) for row in cur.fetchall()]

        updated = []
        for s in suppliers:
            # Delay simulation — 10% chance per cycle (Phase 4 mock)
            # Phase 5 mein real delivery tracking se replace hoga
            if simulate_delay and s['supplier_id'] == delay_supplier_id:
                # OTD temporarily reduce karo delay event par
                # Real system mein: actual delivery timestamp compare karte
                new_otd = float(s['otd_rate']) * 0.92
                cur.execute("""
                    UPDATE hermes_suppliers
                    SET otd_rate = %s,
                        last_delay_at = NOW(),
                        last_updated = NOW()
                    WHERE supplier_id = %s
                """, (round(new_otd, 2), s['supplier_id']))
                s['otd_rate'] = new_otd

            # Score recalculate
            # price_factor already inverted (low cost = high factor)
            score = (
                float(s['otd_rate'])     * 0.6 +
                float(s['quality_rate']) * 0.3 +
                float(s['price_factor']) * 0.1
            )
            score = round(score, 2)

            # Status logic
            # PREFERRED: highest score overall
            # AT_RISK: OTD < 80%
            # ACTIVE: normal
            # SWITCHED: manually overridden (set by reorder_trigger_tool)
            if float(s['otd_rate']) < 80.0:
                status = "AT_RISK"
            else:
                status = s['status'] if s['status'] == 'SWITCHED' else 'ACTIVE'

            cur.execute("""
                UPDATE hermes_suppliers
                SET reliability_score = %s,
                    status = %s,
                    last_updated = NOW()
                WHERE supplier_id = %s
            """, (score, status, s['supplier_id']))

            s['reliability_score'] = score
            s['status'] = status
            updated.append(s)

        # PREFERRED = highest score wala supplier
        # Sirf ek PREFERRED hoga at a time
        if updated:
            best = max(updated, key=lambda x: float(x['reliability_score']))
            cur.execute("""
                UPDATE hermes_suppliers
                SET status = 'PREFERRED'
                WHERE supplier_id = %s
                  AND status != 'SWITCHED'
                  AND status != 'AT_RISK'
            """, (best['supplier_id'],))
            for s in updated:
                if s['supplier_id'] == best['supplier_id']:
                    s['status'] = 'PREFERRED'

        conn.commit()
        return updated
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════
# TOOL 3 — Reorder Trigger
# Kya karta hai: auto-order place karta hai hermes_orders mein
# Logic: best supplier select karta hai by reliability score
# Side effect: inventory last_reorder_at update karta hai
# ══════════════════════════════════════════════════════════
def reorder_trigger_tool(
    component_id: str,
    trigger_reason: str = "REORDER_POINT_BREACH",
    trigger_source: str = "HERMES_AUTO",
    force_supplier_id: Optional[str] = None
) -> dict:
    """
    Ek component ke liye auto-order trigger karta hai.
    Guard: agar last 25 min mein already order hai → skip.
    """
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # ── Duplicate order guard ──────────────────────────
        # Agar is component ka order last 25 min mein already
        # place hua hai → dobara order mat karo
        # Yeh infinite reorder loop prevent karta hai
        cur.execute("""
            SELECT id FROM hermes_orders
            WHERE component_id = %s
              AND status = 'PENDING'
              AND created_at > NOW() - INTERVAL '25 minutes'
            LIMIT 1
        """, (component_id,))
        existing = cur.fetchone()
        if existing:
            return {
                "skipped": True,
                "reason":  f"Pending order already exists for {component_id}"
            }

        # Component data lo
        cur.execute("""
            SELECT * FROM hermes_inventory
            WHERE component_id = %s
        """, (component_id,))
        component = cur.fetchone()
        if not component:
            return {"error": f"Component {component_id} not found"}

        # Best supplier select karo
        if force_supplier_id:
            cur.execute("""
                SELECT * FROM hermes_suppliers
                WHERE supplier_id = %s
            """, (force_supplier_id,))
            supplier = cur.fetchone()
        else:
            cur.execute("""
                SELECT * FROM hermes_suppliers
                WHERE status != 'AT_RISK'
                ORDER BY reliability_score DESC
                LIMIT 1
            """)
            supplier = cur.fetchone()

            if not supplier:
                cur.execute("""
                    SELECT * FROM hermes_suppliers
                    ORDER BY reliability_score DESC
                    LIMIT 1
                """)
                supplier = cur.fetchone()

        if not supplier:
            return {"error": "No supplier available"}

        qty = component['reorder_quantity']
        if trigger_reason == "ORACLE_PREPOSITION":
            qty = int(qty * 1.2)

        total_cost = float(component['unit_cost_eur']) * qty
        expected   = datetime.now(timezone.utc) + timedelta(
            days=component['lead_time_days']
        )
        order_id = (
            f"ORD-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            f"-{component_id[:8].upper()}"
        )

        cur.execute("""
            INSERT INTO hermes_orders (
                order_id, component_id, supplier_id,
                quantity_ordered, unit_cost_eur, total_cost_eur,
                trigger_reason, trigger_source,
                status, expected_delivery
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING', %s
            )
            RETURNING *
        """, (
            order_id, component_id, supplier['supplier_id'],
            qty, float(component['unit_cost_eur']),
            total_cost, trigger_reason, trigger_source, expected
        ))
        order = dict(cur.fetchone())

        cur.execute("""
            UPDATE hermes_inventory
            SET last_reorder_at = NOW(),
                last_updated    = NOW()
            WHERE component_id = %s
        """, (component_id,))

        if component['assigned_supplier'] != supplier['supplier_id']:
            cur.execute("""
                UPDATE hermes_inventory
                SET assigned_supplier = %s,
                    last_updated      = NOW()
                WHERE component_id = %s
            """, (supplier['supplier_id'], component_id))
            cur.execute("""
                UPDATE hermes_suppliers
                SET status       = 'SWITCHED',
                    last_updated = NOW()
                WHERE supplier_id = %s
            """, (component['assigned_supplier'],))
            order['supplier_switched'] = True
            order['previous_supplier'] = component['assigned_supplier']

        conn.commit()
        return order
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════
# TOOL 4 — Demand Forecast Reader
# Kya karta hai: ORACLE ke latest forecast padhta hai
# Source: oracle_forecasts table (Phase 3 ne populate kiya)
# Return: demand signals jo HERMES use karega pre-positioning ke liye
# ══════════════════════════════════════════════════════════
def demand_forecast_reader_tool() -> dict:
    """
    ORACLE ka latest forecast padhta hai.
    Agar koi forecast nahi mila → fallback dict return karta hai.

    Return format:
    {
      'has_signal': True/False,
      'failure_probability': 0.99,
      'bottleneck_machine': 'Machine_C',
      'forecast_horizon_hours': 24,
      'generated_at': datetime,
      'raw_forecast': {...}
    }
    """
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Latest ORACLE forecast lo
        cur.execute("""
            SELECT * FROM oracle_forecasts
            ORDER BY generated_at DESC
            LIMIT 1
        """)
        row = cur.fetchone()

        if not row:
            return {
                "has_signal": False,
                "reason": "No ORACLE forecast available yet"
            }

        forecast_data = row['forecast_json']

        # forecast_json structure (Phase 3 se):
        # { "machines": { "Machine_A": {"failure_prob": 0.12}, ... } }
        # HERMES ko highest failure probability wali machine chahiye

        machines = forecast_data.get("machines", {})
        if not machines:
            return {
                "has_signal": False,
                "reason": "ORACLE forecast has no machine data"
            }

        # Highest failure probability machine dhundho
        bottleneck = max(
            machines.items(),
            key=lambda x: x[1].get("failure_prob", 0)
        )
        machine_name, machine_data = bottleneck
        failure_prob = machine_data.get("failure_prob", 0)

        # Signal threshold: 80% se upar → HERMES action lega
        has_signal = failure_prob >= 0.80

        return {
            "has_signal":           has_signal,
            "failure_probability":  failure_prob,
            "bottleneck_machine":   machine_name,
            "forecast_horizon_hours": row['horizon_hours'],
            "generated_at":         row['generated_at'].isoformat()
                                    if hasattr(row['generated_at'], 'isoformat')
                                    else str(row['generated_at']),
            "raw_forecast":         forecast_data
        }
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════
# TOOL 5 — Stockout Risk Calculator
# Kya karta hai: har component ka risk level recalculate karta hai
# Formula: days_of_stock = current_stock / daily_consumption
# Side effect: DB mein risk_level update karta hai
# ══════════════════════════════════════════════════════════
def stockout_risk_calculator_tool() -> list:
    """
    Saare components ka risk level recalculate karta hai.
    DB mein update karta hai.
    Returns: list of components with updated risk levels
    """
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM hermes_inventory")
        components = [dict(row) for row in cur.fetchall()]

        updated = []
        for c in components:
            # Guard: division by zero nahi hona chahiye
            daily = float(c['daily_consumption'])
            if daily <= 0:
                daily = 1.0

            days_of_stock = float(c['current_stock']) / daily

            # 4-level classification
            if days_of_stock < 3:
                risk = "CRITICAL"
            elif days_of_stock < 7:
                risk = "HIGH"
            elif days_of_stock < 14:
                risk = "MEDIUM"
            else:
                risk = "LOW"

            # DB update
            cur.execute("""
                UPDATE hermes_inventory
                SET risk_level = %s,
                    last_updated = NOW()
                WHERE component_id = %s
            """, (risk, c['component_id']))

            c['risk_level'] = risk
            c['days_of_stock'] = round(days_of_stock, 1)
            updated.append(c)

        conn.commit()
        return updated
    finally:
        conn.close()
