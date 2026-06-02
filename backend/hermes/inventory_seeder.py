"""
CORTEX Phase 4 — HERMES Supply Chain Agent
inventory_seeder.py

Kya karta hai:
  1. 3 naye tables create karta hai PostgreSQL mein
  2. 10 industrial components seed karta hai
  3. 4 suppliers seed karta hai
  4. hermes_orders table empty banata hai (HERMES fill karega)

Run: python3 -m hermes.inventory_seeder
"""

import sys
import os
from datetime import datetime, timezone

# --- DB connection ---
# .env se DATABASE_URL load karna
# psycopg2 directly use karenge — no ORM overhead

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    print("[ERROR] psycopg2 not found.")
    print("Fix: ~/projects/cortex/backend/venv/bin/pip install psycopg2-binary")
    sys.exit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    print("[ERROR] python-dotenv not found.")
    print("Fix: ~/projects/cortex/backend/venv/bin/pip install python-dotenv")
    sys.exit(1)

# ── Load .env ──────────────────────────────────────────────
# .env file backend/ folder mein hona chahiye
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(dotenv_path=env_path)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("[ERROR] DATABASE_URL not found in .env")
    print("Expected format: postgresql://cortex_user:password@localhost/cortex_db")
    sys.exit(1)

# ── Table Creation SQL ──────────────────────────────────────

CREATE_INVENTORY_TABLE = """
DROP TABLE IF EXISTS hermes_inventory CASCADE;
CREATE TABLE hermes_inventory (
    id                  SERIAL PRIMARY KEY,
    component_id        VARCHAR(50)  NOT NULL UNIQUE,
    display_name        VARCHAR(100) NOT NULL,
    current_stock       INTEGER      NOT NULL,
    safety_stock_level  INTEGER      NOT NULL,
    reorder_point       INTEGER      NOT NULL,
    reorder_quantity    INTEGER      NOT NULL,
    unit_cost_eur       NUMERIC(10,2) NOT NULL,
    lead_time_days      INTEGER      NOT NULL,
    assigned_supplier   VARCHAR(10)  NOT NULL,
    daily_consumption   NUMERIC(8,2) NOT NULL,
    risk_level          VARCHAR(20)  NOT NULL DEFAULT 'LOW',
    last_reorder_at     TIMESTAMP WITH TIME ZONE,
    last_updated        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
"""

# Indexes — fast lookup by risk_level aur supplier
CREATE_INVENTORY_INDEXES = """
CREATE INDEX idx_hermes_inv_risk
    ON hermes_inventory(risk_level);
CREATE INDEX idx_hermes_inv_supplier
    ON hermes_inventory(assigned_supplier);
"""

CREATE_SUPPLIERS_TABLE = """
DROP TABLE IF EXISTS hermes_suppliers CASCADE;
CREATE TABLE hermes_suppliers (
    id                  SERIAL PRIMARY KEY,
    supplier_id         VARCHAR(10)  NOT NULL UNIQUE,
    supplier_name       VARCHAR(100) NOT NULL,
    otd_rate            NUMERIC(5,2) NOT NULL,
    quality_rate        NUMERIC(5,2) NOT NULL,
    price_factor        NUMERIC(5,2) NOT NULL,
    reliability_score   NUMERIC(5,2) NOT NULL,
    status              VARCHAR(20)  NOT NULL DEFAULT 'ACTIVE',
    active_components   INTEGER      NOT NULL DEFAULT 0,
    last_delay_at       TIMESTAMP WITH TIME ZONE,
    last_updated        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
"""

CREATE_ORDERS_TABLE = """
DROP TABLE IF EXISTS hermes_orders CASCADE;
CREATE TABLE hermes_orders (
    id                  SERIAL PRIMARY KEY,
    order_id            VARCHAR(50)  NOT NULL UNIQUE,
    component_id        VARCHAR(50)  NOT NULL,
    supplier_id         VARCHAR(10)  NOT NULL,
    quantity_ordered    INTEGER      NOT NULL,
    unit_cost_eur       NUMERIC(10,2) NOT NULL,
    total_cost_eur      NUMERIC(10,2) NOT NULL,
    trigger_reason      VARCHAR(50)  NOT NULL,
    trigger_source      VARCHAR(30)  NOT NULL DEFAULT 'HERMES_AUTO',
    status              VARCHAR(20)  NOT NULL DEFAULT 'PENDING',
    expected_delivery   TIMESTAMP WITH TIME ZONE,
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
"""

CREATE_ORDERS_INDEXES = """
CREATE INDEX idx_hermes_orders_component
    ON hermes_orders(component_id);
CREATE INDEX idx_hermes_orders_status
    ON hermes_orders(status);
CREATE INDEX idx_hermes_orders_created
    ON hermes_orders(created_at DESC);
"""

# ── Seed Data ───────────────────────────────────────────────

# 4 Suppliers
# reliability_score = (otd_rate * 0.6) + (quality_rate * 0.3) + (price_factor * 0.1)
# price_factor: lower cost = higher factor (inverted)
# Supplier A: score = (94*0.6) + (96*0.3) + (70*0.1) = 56.4+28.8+7.0 = 92.2
# Supplier B: score = (87*0.6) + (91*0.3) + (80*0.1) = 52.2+27.3+8.0 = 87.5
# Supplier C: score = (73*0.6) + (85*0.3) + (90*0.1) = 43.8+25.5+9.0 = 78.3
# Supplier D: score = (91*0.6) + (93*0.3) + (60*0.1) = 54.6+27.9+6.0 = 88.5

SUPPLIERS = [
    {
        "supplier_id":       "SUP_A",
        "supplier_name":     "PrecisionParts GmbH",
        "otd_rate":          94.0,   # On-Time Delivery %
        "quality_rate":      96.0,   # Quality acceptance %
        "price_factor":      70.0,   # Lower cost = higher score contribution
        "reliability_score": 92.2,   # Pre-calculated
        "status":            "PREFERRED",
        "active_components": 4,
    },
    {
        "supplier_id":       "SUP_B",
        "supplier_name":     "AutomationSupply AG",
        "otd_rate":          87.0,
        "quality_rate":      91.0,
        "price_factor":      80.0,
        "reliability_score": 87.5,
        "status":            "ACTIVE",
        "active_components": 3,
    },
    {
        "supplier_id":       "SUP_C",
        "supplier_name":     "IndustrialDirect KG",
        "otd_rate":          73.0,
        "quality_rate":      85.0,
        "price_factor":      90.0,
        "reliability_score": 78.3,
        "status":            "AT_RISK",   # OTD < 80% → AT_RISK
        "active_components": 2,
    },
    {
        "supplier_id":       "SUP_D",
        "supplier_name":     "TechComponents EU",
        "otd_rate":          91.0,
        "quality_rate":      93.0,
        "price_factor":      60.0,
        "reliability_score": 88.5,
        "status":            "ACTIVE",
        "active_components": 1,
    },
]

# 10 Industrial Components
# daily_consumption: realistic factory usage per day
# Safety stock, ROP, reorder_qty: calculated values
# risk_level: computed from days_of_stock at seed time

COMPONENTS = [
    {
        "component_id":      "precision_bearings_v2",
        "display_name":      "Precision Bearings V2",
        "current_stock":     45,
        "safety_stock_level":20,
        "reorder_point":     35,
        "reorder_quantity":  100,
        "unit_cost_eur":     12.50,
        "lead_time_days":    3,
        "assigned_supplier": "SUP_A",
        "daily_consumption": 4.0,
        # days_of_stock = 45/4 = 11.25 → MEDIUM
        "risk_level":        "MEDIUM",
    },
    {
        "component_id":      "servo_motors_type_a",
        "display_name":      "Servo Motors Type-A",
        "current_stock":     18,
        "safety_stock_level":10,
        "reorder_point":     25,
        "reorder_quantity":  30,
        "unit_cost_eur":     145.00,
        "lead_time_days":    5,
        "assigned_supplier": "SUP_A",
        "daily_consumption": 2.0,
        # days_of_stock = 18/2 = 9 → MEDIUM
        "risk_level":        "MEDIUM",
    },
    {
        "component_id":      "hydraulic_seals_set",
        "display_name":      "Hydraulic Seals Set",
        "current_stock":     12,
        "safety_stock_level":15,
        "reorder_point":     30,
        "reorder_quantity":  80,
        "unit_cost_eur":     8.75,
        "lead_time_days":    4,
        "assigned_supplier": "SUP_B",
        "daily_consumption": 3.5,
        # days_of_stock = 12/3.5 = 3.4 → HIGH
        # Also: current_stock < safety_stock → needs immediate attention
        "risk_level":        "HIGH",
    },
    {
        "component_id":      "control_pcb_unit",
        "display_name":      "Control PCB Unit",
        "current_stock":     8,
        "safety_stock_level":5,
        "reorder_point":     12,
        "reorder_quantity":  20,
        "unit_cost_eur":     89.90,
        "lead_time_days":    7,
        "assigned_supplier": "SUP_A",
        "daily_consumption": 1.0,
        # days_of_stock = 8/1 = 8 → MEDIUM
        # BUT: stock < reorder_point (8 < 12) → HERMES will trigger order
        "risk_level":        "MEDIUM",
    },
    {
        "component_id":      "pneumatic_cylinders",
        "display_name":      "Pneumatic Cylinders",
        "current_stock":     67,
        "safety_stock_level":25,
        "reorder_point":     40,
        "reorder_quantity":  120,
        "unit_cost_eur":     34.20,
        "lead_time_days":    3,
        "assigned_supplier": "SUP_B",
        "daily_consumption": 5.0,
        # days_of_stock = 67/5 = 13.4 → MEDIUM (borderline)
        "risk_level":        "MEDIUM",
    },
    {
        "component_id":      "encoder_discs_100ppr",
        "display_name":      "Encoder Discs 100PPR",
        "current_stock":     155,
        "safety_stock_level":30,
        "reorder_point":     50,
        "reorder_quantity":  200,
        "unit_cost_eur":     6.30,
        "lead_time_days":    2,
        "assigned_supplier": "SUP_C",
        "daily_consumption": 6.0,
        # days_of_stock = 155/6 = 25.8 → LOW ✅
        "risk_level":        "LOW",
    },
    {
        "component_id":      "cooling_fans_48v",
        "display_name":      "Cooling Fans 48V",
        "current_stock":     5,
        "safety_stock_level":8,
        "reorder_point":     15,
        "reorder_quantity":  40,
        "unit_cost_eur":     22.00,
        "lead_time_days":    4,
        "assigned_supplier": "SUP_D",
        "daily_consumption": 1.5,
        # days_of_stock = 5/1.5 = 3.3 → HIGH
        # stock < safety_stock AND < reorder_point → HERMES immediate action
        "risk_level":        "HIGH",
    },
    {
        "component_id":      "power_supply_24v",
        "display_name":      "Power Supply 24V",
        "current_stock":     2,
        "safety_stock_level":5,
        "reorder_point":     10,
        "reorder_quantity":  25,
        "unit_cost_eur":     67.50,
        "lead_time_days":    5,
        "assigned_supplier": "SUP_A",
        "daily_consumption": 0.8,
        # days_of_stock = 2/0.8 = 2.5 → CRITICAL ⚠️
        "risk_level":        "CRITICAL",
    },
    {
        "component_id":      "conveyor_belts_type3",
        "display_name":      "Conveyor Belts Type-3",
        "current_stock":     89,
        "safety_stock_level":20,
        "reorder_point":     35,
        "reorder_quantity":  60,
        "unit_cost_eur":     18.40,
        "lead_time_days":    3,
        "assigned_supplier": "SUP_B",
        "daily_consumption": 3.0,
        # days_of_stock = 89/3 = 29.7 → LOW ✅
        "risk_level":        "LOW",
    },
    {
        "component_id":      "sensor_modules_temp",
        "display_name":      "Sensor Modules Temp",
        "current_stock":     31,
        "safety_stock_level":12,
        "reorder_point":     20,
        "reorder_quantity":  50,
        "unit_cost_eur":     15.80,
        "lead_time_days":    2,
        "assigned_supplier": "SUP_C",
        "daily_consumption": 2.5,
        # days_of_stock = 31/2.5 = 12.4 → MEDIUM
        "risk_level":        "MEDIUM",
    },
]


# ── Main Seeder Function ────────────────────────────────────

def run_seeder():
    print("=" * 60)
    print("CORTEX HERMES — Inventory Seeder")
    print("=" * 60)

    # DB connect
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        cur = conn.cursor(cursor_factory=RealDictCursor)
        print("[OK] PostgreSQL connected")
    except Exception as e:
        print(f"[ERROR] DB connection failed: {e}")
        sys.exit(1)

    try:
        # ── Create Tables ──────────────────────────────────
        print("\n[1/5] Creating hermes_inventory table...")
        cur.execute(CREATE_INVENTORY_TABLE)
        cur.execute(CREATE_INVENTORY_INDEXES)
        print("      hermes_inventory ✅")

        print("[2/5] Creating hermes_suppliers table...")
        cur.execute(CREATE_SUPPLIERS_TABLE)
        print("      hermes_suppliers ✅")

        print("[3/5] Creating hermes_orders table...")
        cur.execute(CREATE_ORDERS_TABLE)
        cur.execute(CREATE_ORDERS_INDEXES)
        print("      hermes_orders    ✅")

        # ── Seed Suppliers ─────────────────────────────────
        print("\n[4/5] Seeding 4 suppliers...")
        for s in SUPPLIERS:
            cur.execute("""
                INSERT INTO hermes_suppliers (
                    supplier_id, supplier_name,
                    otd_rate, quality_rate, price_factor,
                    reliability_score, status, active_components
                ) VALUES (
                    %(supplier_id)s, %(supplier_name)s,
                    %(otd_rate)s, %(quality_rate)s, %(price_factor)s,
                    %(reliability_score)s, %(status)s, %(active_components)s
                )
            """, s)
            print(f"      {s['supplier_id']} — {s['supplier_name']} "
                  f"[Score: {s['reliability_score']}] ✅")

        # ── Seed Components ────────────────────────────────
        print("\n[5/5] Seeding 10 components...")
        for c in COMPONENTS:
            cur.execute("""
                INSERT INTO hermes_inventory (
                    component_id, display_name,
                    current_stock, safety_stock_level,
                    reorder_point, reorder_quantity,
                    unit_cost_eur, lead_time_days,
                    assigned_supplier, daily_consumption,
                    risk_level
                ) VALUES (
                    %(component_id)s, %(display_name)s,
                    %(current_stock)s, %(safety_stock_level)s,
                    %(reorder_point)s, %(reorder_quantity)s,
                    %(unit_cost_eur)s, %(lead_time_days)s,
                    %(assigned_supplier)s, %(daily_consumption)s,
                    %(risk_level)s
                )
            """, c)
            days = c['current_stock'] / c['daily_consumption']
            print(f"      {c['component_id']:<30} "
                  f"stock={c['current_stock']:>3} "
                  f"days={days:>5.1f} "
                  f"[{c['risk_level']}]")

        # ── Commit ─────────────────────────────────────────
        conn.commit()
        print("\n" + "=" * 60)
        print("✅ HERMES database seeded successfully!")
        print("=" * 60)

        # ── Summary ────────────────────────────────────────
        cur.execute("SELECT risk_level, COUNT(*) as cnt "
                    "FROM hermes_inventory "
                    "GROUP BY risk_level ORDER BY risk_level")
        rows = cur.fetchall()
        print("\nRisk Level Summary:")
        for row in rows:
            print(f"  {row['risk_level']:<10} : {row['cnt']} components")

        cur.execute("SELECT status, COUNT(*) as cnt "
                    "FROM hermes_suppliers "
                    "GROUP BY status ORDER BY status")
        rows = cur.fetchall()
        print("\nSupplier Status Summary:")
        for row in rows:
            print(f"  {row['status']:<12} : {row['cnt']} suppliers")

        print("\nNext step: python3 -m hermes.hermes_tools")
        print("=" * 60)

    except Exception as e:
        conn.rollback()
        print(f"\n[ERROR] Seeder failed: {e}")
        print("Changes rolled back.")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    run_seeder()
