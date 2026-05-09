"""
main.py — CORTEX FastAPI Application Entry Point

ENDPOINTS:
  GET  /              — health check
  GET  /health        — detailed health
  GET  /agents        — master status + agent info
  GET  /agents/logs   — recent sentinel logs
  WS   /ws            — WebSocket real-time stream

STARTUP SEQUENCE:
  1. Database tables verified
  2. Isolation Forest model trained (if not exists)
  3. APScheduler started (pipeline every 10s)
  4. FastAPI ready to serve
"""

import os
import sys
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from database.init_db import init_db
from database.crud import get_recent_sentinel_logs
from crew.cortex_crew import get_master
from ws_broadcaster.broadcaster import manager
from scheduler.agent_scheduler import start_scheduler, stop_scheduler
from ml.isolation_forest import train, MODEL_PATH
from api.routes import router as phase2_router


# ── Lifespan (startup + shutdown) ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── STARTUP ──
    print("[CORTEX] Starting up...")

    print("[CORTEX] Initializing database...")
    init_db()

    if not os.path.exists(MODEL_PATH):
        print("[CORTEX] Model not found — training Isolation Forest...")
        train(n_samples=300)
    else:
        print("[CORTEX] Model found — skipping training")

    print("[CORTEX] Starting scheduler...")
    start_scheduler()

    print("[CORTEX] ✅ Ready.")
    yield

    # ── SHUTDOWN ──
    print("[CORTEX] Shutting down...")
    stop_scheduler()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
app.include_router(phase2_router)
    title="CORTEX — Autonomous Industrial Intelligence",
    version="0.1.0-phase1",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── HTTP Endpoints ────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "system": "CORTEX",
        "tagline": "Six AI minds. One factory brain.",
        "status": "online",
        "phase": "1",
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "model_ready": os.path.exists(MODEL_PATH),
        "scheduler_running": True,
    }


@app.get("/agents")
async def agents_status():
    """Return CORTEX_MASTER status + all agent info."""
    master = get_master()
    status = master.get_status()
    return {
        "master": status,
        "agents": [
            {"id": "SENTINEL", "status": "active", "role": "Anomaly Detection"},
            {"id": "SCRIBE",   "status": "active", "role": "Intelligence Reporter"},
            {"id": "ORACLE",   "status": "phase3",  "role": "Predictive Intelligence"},
            {"id": "GUARDIAN", "status": "phase4",  "role": "Cybersecurity Monitor"},
            {"id": "OPTIMUS",  "status": "phase4",  "role": "Process Optimization"},
            {"id": "HERMES",   "status": "phase4",  "role": "Supply Chain Intelligence"},
        ]
    }


@app.get("/agents/logs")
async def recent_logs():
    """Return 10 most recent SENTINEL detection logs."""
    logs = get_recent_sentinel_logs(limit=10)
    return {
        "logs": [
            {
                "id":               log.id,
                "status":           log.status,
                "anomaly_score":    log.anomaly_score,
                "detection_method": log.detection_method,
                "flagged_sensors":  log.flagged_sensors,
                "summary":          log.summary,
                "timestamp":        log.timestamp.isoformat(),
            }
            for log in logs
        ]
    }


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time pipeline updates.
    Frontend connects here to receive live SENTINEL results.
    """
    await manager.connect(websocket)
    try:
        # Send immediate status on connect
        master = get_master()
        await websocket.send_json({
            "event": "connected",
            "message": "CORTEX WebSocket active",
            "master_stats": master.get_status(),
        })
        # Keep connection alive — wait for disconnect
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
