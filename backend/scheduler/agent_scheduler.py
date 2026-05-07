"""
agent_scheduler.py — APScheduler setup for CORTEX.

Runs SENTINEL→MASTER→SCRIBE pipeline every 10 seconds.
Broadcasts results via WebSocket after each cycle.

WHY APSCHEDULER NOT CELERY?
Celery requires Redis as broker + separate worker process.
On 3.3GB RAM, that's too heavy.
APScheduler runs inside FastAPI's process — zero extra overhead.
"""

import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from crew.cortex_crew import get_master
from ws_broadcaster.broadcaster import manager

scheduler = AsyncIOScheduler()


async def _run_pipeline_and_broadcast():
    """
    Called every 10 seconds by APScheduler.
    Runs one MASTER cycle and broadcasts result to WebSocket clients.
    """
    try:
        master = get_master()
        result = master.run_cycle()

        # Add agent statuses for frontend display
        broadcast_payload = {
            "event":      "cycle_complete",
            "cycle_id":   result["cycle_id"],
            "priority":   result["priority"],
            "status":     result["sentinel_status"],
            "score":      result["anomaly_score"],
            "method":     result["detection_method"],
            "flagged":    result["flagged_sensors"],
            "summary":    result["summary"],
            "timestamp":  result["timestamp"],
            "master_stats": get_master().get_status(),
        }

        await manager.broadcast(broadcast_payload)

    except Exception as e:
        print(f"[SCHEDULER] Error in pipeline: {e}")


def start_scheduler():
    scheduler.add_job(
        _run_pipeline_and_broadcast,
        trigger="interval",
        seconds=10,
        id="cortex_pipeline",
        replace_existing=True,
    )
    scheduler.start()
    print("[SCHEDULER] APScheduler started — pipeline runs every 10s")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        print("[SCHEDULER] APScheduler stopped")
