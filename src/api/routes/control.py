"""
Control API endpoints.

GET /api/status - Get bot status (running, PID, uptime)
POST /api/restart - Send SIGTERM to bot (expects supervisor to restart)
"""

import os
import signal
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter()

PID_PATH = Path("/tmp/polymarket_bot.pid")
METRICS_PATH = Path("/tmp/polymarket_metrics.json")


def get_pid() -> int | None:
    """Get bot PID from file"""
    if not PID_PATH.exists():
        return None
    try:
        return int(PID_PATH.read_text().strip())
    except Exception:
        return None


def is_process_running(pid: int) -> bool:
    """Check if process with given PID is running"""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@router.get("/status")
async def get_status() -> dict:
    """Get bot status"""
    pid = get_pid()
    running = pid is not None and is_process_running(pid)

    status = {
        "running": running,
        "pid": pid,
    }

    # Get uptime from metrics file if available
    if METRICS_PATH.exists():
        try:
            import json

            with open(METRICS_PATH) as f:
                metrics = json.load(f)
                status["uptime_sec"] = metrics.get("uptime_sec", 0)
                status["start_time"] = metrics.get("start_time")
                status["last_update"] = metrics.get("timestamp")
        except Exception:
            pass

    return status


@router.post("/restart")
async def restart_bot() -> dict:
    """Send SIGTERM to bot. Supervisor (K8s/systemd) should restart it."""
    pid = get_pid()

    if pid is None:
        raise HTTPException(status_code=404, detail="Bot PID not found")

    if not is_process_running(pid):
        raise HTTPException(status_code=404, detail="Bot process not running")

    try:
        os.kill(pid, signal.SIGTERM)
        return {"status": "ok", "message": f"SIGTERM sent to PID {pid}"}
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to send signal: {e}")


@router.post("/refresh-markets")
async def refresh_markets() -> dict:
    """Force refresh markets. Sends SIGUSR1 to bot to trigger market refresh."""
    pid = get_pid()

    if pid is None:
        raise HTTPException(status_code=404, detail="Bot PID not found")

    if not is_process_running(pid):
        raise HTTPException(status_code=404, detail="Bot process not running")

    try:
        os.kill(pid, signal.SIGUSR1)
        return {"status": "ok", "message": f"Refresh signal sent to PID {pid}"}
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to send signal: {e}")
