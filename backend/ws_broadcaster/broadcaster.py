"""
broadcaster.py — WebSocket connection manager.

WHY BROADCASTER PATTERN?
Multiple frontend tabs can connect simultaneously.
Broadcaster maintains a list of all active connections.
When SENTINEL fires, it broadcasts to ALL connected clients at once.
"""

import json
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        # List of all currently connected WebSocket clients
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"[WS] Client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        print(f"[WS] Client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, data: dict):
        """Send data to ALL connected clients."""
        if not self.active_connections:
            return
        message = json.dumps(data)
        dead = []
        for ws in self.active_connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


# Singleton — shared across routers and scheduler
manager = ConnectionManager()
