"""
Metrics API endpoints.

GET /api/metrics - Get metrics snapshot
WS /ws/metrics - WebSocket for live metrics updates
"""

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

METRICS_PATH = Path("/tmp/polymarket_metrics.json")


def load_metrics() -> dict:
    """Load metrics from JSON file"""
    if not METRICS_PATH.exists():
        return {"error": "No metrics available", "bot_running": False}
    try:
        with open(METRICS_PATH) as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e), "bot_running": False}


@router.get("/metrics")
async def get_metrics() -> dict:
    """Get current metrics snapshot"""
    metrics = load_metrics()
    return {"metrics": metrics}


@router.websocket("/ws/metrics")
async def websocket_metrics(websocket: WebSocket):
    """WebSocket endpoint for live metrics updates (1s interval)"""
    await websocket.accept()
    try:
        while True:
            metrics = load_metrics()
            await websocket.send_json({"metrics": metrics})
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
