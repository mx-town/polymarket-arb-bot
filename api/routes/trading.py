"""
Trading API endpoints.

Serves trading bot control endpoints:
- GET /api/trading/status - Get bot status
- POST /api/trading/start - Start bot with optional config overrides
- POST /api/trading/stop - Stop bot (optional force parameter)
- POST /api/trading/restart - Restart bot with optional new config
- GET /api/trading/metrics - Get current metrics from file
"""

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.controllers.bot_controller import BotController
from trading.utils.logging import get_logger

logger = get_logger("trading_api")

router = APIRouter(prefix="/api/trading", tags=["trading"])

METRICS_PATH = Path("/tmp/polymarket_metrics.json")


# =============================================================================
# Request/Response Models
# =============================================================================


class TradingStartRequest(BaseModel):
    """Request body for starting the trading bot."""

    strategy: str = "lag_arb"
    dry_run: bool = True
    config_overrides: dict = {}


class TradingStopRequest(BaseModel):
    """Request body for stopping the trading bot."""

    force: bool = False


class TradingStatusResponse(BaseModel):
    """Response model for bot status."""

    is_running: bool
    pid: int | None
    uptime_sec: float | None
    status: str  # starting, running, stopped, failed
    started_at: str | None


# =============================================================================
# REST Endpoints
# =============================================================================


@router.get("/status", response_model=TradingStatusResponse)
async def get_trading_status() -> TradingStatusResponse:
    """Get current bot status (running/stopped, metrics)."""
    controller = BotController.get_instance()
    status = controller.get_status()
    return TradingStatusResponse(**status)


@router.post("/start")
async def start_trading(request: TradingStartRequest) -> dict:
    """
    Start the trading bot with optional config overrides.

    Returns 409 if bot is already running.
    """
    controller = BotController.get_instance()

    if controller.is_running:
        raise HTTPException(status_code=409, detail="Bot already running")

    try:
        # Build config overrides from request
        config_overrides = request.config_overrides.copy()
        config_overrides["strategy"] = request.strategy
        config_overrides["dry_run"] = request.dry_run

        status = await controller.start(config_overrides)
        logger.info("TRADING_STARTED", f"strategy={request.strategy} dry_run={request.dry_run}")
        return {"status": status}
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error("START_ERROR", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop")
async def stop_trading(request: TradingStopRequest) -> dict:
    """
    Stop the trading bot.

    Args:
        request: Request body with optional force parameter

    Returns:
        Status dict
    """
    controller = BotController.get_instance()

    if not controller.is_running:
        return {
            "status": controller.get_status(),
            "message": "Bot is not running",
        }

    try:
        status = await controller.stop(force=request.force)
        logger.info("TRADING_STOPPED", f"force={request.force}")
        return {"status": status}
    except Exception as e:
        logger.error("STOP_ERROR", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/restart")
async def restart_trading(request: TradingStartRequest) -> dict:
    """
    Restart the bot with optional new config.

    Stops current instance (if running) and starts a new one.
    """
    controller = BotController.get_instance()

    try:
        # Build config overrides from request
        config_overrides = request.config_overrides.copy()
        config_overrides["strategy"] = request.strategy
        config_overrides["dry_run"] = request.dry_run

        status = await controller.restart(config_overrides)
        logger.info("TRADING_RESTARTED", f"strategy={request.strategy} dry_run={request.dry_run}")
        return {"status": status}
    except Exception as e:
        logger.error("RESTART_ERROR", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics")
async def get_trading_metrics() -> dict:
    """Get current metrics from /tmp/polymarket_metrics.json."""
    if not METRICS_PATH.exists():
        return {"metrics": None, "error": "Metrics file not found"}

    try:
        with open(METRICS_PATH) as f:
            metrics = json.load(f)
        return {"metrics": metrics}
    except Exception as e:
        logger.error("METRICS_READ_ERROR", str(e))
        raise HTTPException(status_code=500, detail=f"Failed to read metrics: {e}")
