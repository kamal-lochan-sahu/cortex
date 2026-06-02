"""
CORTEX Phase 4 — HERMES Supply Chain Agent
hermes_router.py

4 API endpoints:
  GET  /api/hermes/inventory  — all 10 components
  GET  /api/hermes/suppliers  — all 4 suppliers
  GET  /api/hermes/orders     — recent + pending orders
  POST /api/hermes/reorder    — manual reorder trigger
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv

from hermes.hermes_tools import reorder_trigger_tool

# ── Setup ──────────────────────────────────────────────────
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(dotenv_path=env_path)
DATABASE_URL = os.getenv("DATABASE_URL")

router = APIRouter(prefix="/api/hermes", tags=["hermes"])


def get_conn():
    return psycopg2.connect(DATABASE_URL)


# ── Request Schema ─────────────────────────────────────────
class ReorderRequest(BaseModel):
    component_id:      str
    force_supplier_id: Optional[str] = None


# ══════════════════════════════════════════════════════════
# GET /api/hermes/inventory
# Saare 10 components ka stock + risk status
# Frontend: InventoryGauge ke liye
# ══════════════════════════════════════════════════════════
@router.get("/inventory")
def get_inventory():
    """
    Returns all 10 components with:
      - current_stock, safety_stock_level, reorder_point
      - risk_level (CRITICAL/HIGH/MEDIUM/LOW)
      - days_of_stock (calculated)
      - assigned_supplier
      - pending_order (bool — kya order already placed hai)
    """
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Inventory data
        cur.execute("""
            SELECT
                i.*,
                ROUND(
                    i.current_stock::numeric /
                    NULLIF(i.daily_consumption, 0),
                    1
                ) AS days_of_stock,
                CASE
                    WHEN EXISTS (
                        SELECT 1 FROM hermes_orders o
                        WHERE o.component_id = i.component_id
                          AND o.status = 'PENDING'
                    ) THEN true
                    ELSE false
                END AS pending_order
            FROM hermes_inventory i
            ORDER BY
                CASE i.risk_level
                    WHEN 'CRITICAL' THEN 1
                    WHEN 'HIGH'     THEN 2
                    WHEN 'MEDIUM'   THEN 3
                    WHEN 'LOW'      THEN 4
                END,
                i.current_stock ASC
        """)
        rows = [dict(r) for r in cur.fetchall()]

        # Numeric fields serialize karo
        for r in rows:
            r['unit_cost_eur']     = float(r['unit_cost_eur'])
            r['daily_consumption'] = float(r['daily_consumption'])
            r['days_of_stock']     = float(r['days_of_stock']) \
                                     if r['days_of_stock'] else 0.0

        # Summary stats — frontend TopBar ke liye
        summary = {
            "total":    len(rows),
            "critical": sum(1 for r in rows if r['risk_level'] == 'CRITICAL'),
            "high":     sum(1 for r in rows if r['risk_level'] == 'HIGH'),
            "medium":   sum(1 for r in rows if r['risk_level'] == 'MEDIUM'),
            "low":      sum(1 for r in rows if r['risk_level'] == 'LOW'),
        }

        return {"components": rows, "summary": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════
# GET /api/hermes/suppliers
# 4 suppliers ka reliability score + status
# Frontend: SupplierMatrix ke liye
# ══════════════════════════════════════════════════════════
@router.get("/suppliers")
def get_suppliers():
    """
    Returns all 4 suppliers with:
      - reliability_score, otd_rate, quality_rate
      - status (PREFERRED/ACTIVE/AT_RISK/SWITCHED)
      - active_components count
      - last_delay_at (null if no recent delay)
    """
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT
                s.*,
                COUNT(i.component_id) AS active_components_live
            FROM hermes_suppliers s
            LEFT JOIN hermes_inventory i
                ON i.assigned_supplier = s.supplier_id
            GROUP BY s.id
            ORDER BY s.reliability_score DESC
        """)
        rows = [dict(r) for r in cur.fetchall()]

        for r in rows:
            r['otd_rate']          = float(r['otd_rate'])
            r['quality_rate']      = float(r['quality_rate'])
            r['price_factor']      = float(r['price_factor'])
            r['reliability_score'] = float(r['reliability_score'])
            # last_delay_at datetime serialize
            if r.get('last_delay_at'):
                r['last_delay_at'] = r['last_delay_at'].isoformat()
            if r.get('last_updated'):
                r['last_updated'] = r['last_updated'].isoformat()

        return {"suppliers": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════
# GET /api/hermes/orders
# Recent + pending orders
# Frontend: Orders log ke liye
# ══════════════════════════════════════════════════════════
@router.get("/orders")
def get_orders(limit: int = 20):
    """
    Returns recent orders (default: last 20).
    Sorted by created_at DESC — newest first.
    """
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT
                o.*,
                i.display_name AS component_display_name,
                s.supplier_name
            FROM hermes_orders o
            LEFT JOIN hermes_inventory i
                ON i.component_id = o.component_id
            LEFT JOIN hermes_suppliers s
                ON s.supplier_id = o.supplier_id
            ORDER BY o.created_at DESC
            LIMIT %s
        """, (limit,))
        rows = [dict(r) for r in cur.fetchall()]

        for r in rows:
            r['unit_cost_eur']  = float(r['unit_cost_eur'])
            r['total_cost_eur'] = float(r['total_cost_eur'])
            if r.get('created_at'):
                r['created_at'] = r['created_at'].isoformat()
            if r.get('expected_delivery'):
                r['expected_delivery'] = r['expected_delivery'].isoformat()

        # Pending orders count
        pending = sum(1 for r in rows if r['status'] == 'PENDING')

        return {
            "orders":        rows,
            "total_shown":   len(rows),
            "pending_count": pending
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════
# POST /api/hermes/reorder
# Manual reorder trigger — human-in-loop override
# Dashboard se trigger kar sakte hain
# ══════════════════════════════════════════════════════════
@router.post("/reorder")
def manual_reorder(req: ReorderRequest):
    """
    Human manually ek component ka reorder trigger kar sakta hai.
    force_supplier_id optional — specific supplier choose kar sakte ho.

    Body: { "component_id": "power_supply_24v" }
    or:   { "component_id": "power_supply_24v", "force_supplier_id": "SUP_D" }
    """
    result = reorder_trigger_tool(
        component_id      = req.component_id,
        trigger_reason    = "MANUAL_OVERRIDE",
        trigger_source    = "DASHBOARD_HUMAN",
        force_supplier_id = req.force_supplier_id
    )

    if result.get("skipped"):
        # Pending order already hai — inform karo but don't error
        return {
            "status":  "skipped",
            "message": f"Pending order already exists for {req.component_id}",
            "detail":  result
        }

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    # Datetime serialize
    if result.get('created_at'):
        result['created_at'] = result['created_at'].isoformat()
    if result.get('expected_delivery'):
        result['expected_delivery'] = result['expected_delivery'].isoformat()
    if result.get('unit_cost_eur'):
        result['unit_cost_eur'] = float(result['unit_cost_eur'])
    if result.get('total_cost_eur'):
        result['total_cost_eur'] = float(result['total_cost_eur'])

    return {
        "status": "success",
        "order":  result
    }
